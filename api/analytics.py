"""
Vercel Serverless Function: GET /api/analytics
External Analytics Retrieval API with:
  - Constant-time Bearer / X-API-Key authentication (supports comma-separated key rotation)
  - Configurable CORS allowlist + preflight caching
  - MySQL-backed atomic fixed-window rate limiting + RFC rate-limit headers
  - Vercel Edge Cache headers (s-maxage, stale-while-revalidate) + ETag / 304 Not Modified
  - Modular dataset selection (?include=rollups,kpi,rankings,live or ?include=all)
  - Date range & window filtering (?start_date=YYYY-MM-DD&end_date=YYYY-MM-DD or ?days=30)
  - Discord 64-bit snowflake stringification to prevent IEEE-754 JS precision loss
"""

from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from datetime import datetime, timedelta, timezone, date
import decimal
import hashlib
import hmac
import json
import os
import re
import sys
import time
import uuid
import pymysql
import pymysql.cursors

# Philippine Standard Time (UTC+8) — matches AnalyticsService
PHT = timezone(timedelta(hours=8))

# Validation constants
VALID_SECTIONS = {"rollups", "kpi", "rankings", "live"}
DEFAULT_SECTIONS = {"rollups", "kpi"}
MAX_DAYS = 365
DEFAULT_DAYS = 30
MAX_RANKING_LIMIT = 25
DEFAULT_RANKING_LIMIT = 5

# Rate limiting defaults (overridable via env vars)
DEFAULT_RATE_LIMIT = 60       # requests per window
DEFAULT_RATE_WINDOW = 60      # window size in seconds

_RAW_ID_RE = re.compile(r"^\d{17,20}$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _is_raw_id(val) -> bool:
    """Return True if value looks like an unresolved Discord snowflake ID."""
    if val is None:
        return True
    return bool(_RAW_ID_RE.fullmatch(str(val)))


def _json_default(obj):
    """Safe JSON serializer for MySQL Decimal, datetime, date, and bytes."""
    if isinstance(obj, decimal.Decimal):
        return int(obj) if obj == obj.to_integral_value() else float(obj)
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, bytes):
        return obj.decode("utf-8", errors="replace")
    return str(obj)


def _str_id(val) -> str | None:
    """Convert 64-bit Discord snowflakes to strings to prevent JS 53-bit precision loss."""
    return str(val) if val is not None else None


class ApiValidationError(Exception):
    """Raised when query parameters fail validation (returns HTTP 400)."""
    pass


class handler(BaseHTTPRequestHandler):

    # Suppress default BaseHTTPRequestHandler stdout logging to avoid leaking query strings
    def log_message(self, fmt, *args):
        return

    # ─── Security & CORS Helpers ─────────────────────────────────────

    def _get_allowed_origin(self) -> tuple[str | None, bool]:
        """
        Evaluate CORS Origin against ANALYTICS_ALLOWED_ORIGINS env var.
        Returns (origin_header_value, is_wildcard).
        """
        raw_origins = os.environ.get("ANALYTICS_ALLOWED_ORIGINS", "*").strip()
        if not raw_origins or raw_origins == "*":
            return "*", True

        allowed = {o.strip().rstrip("/") for o in raw_origins.split(",") if o.strip()}
        req_origin = (self.headers.get("Origin") or "").strip().rstrip("/")
        if req_origin and req_origin in allowed:
            return req_origin, False
        return None, False

    def _send_standard_headers(
        self,
        rate_info: dict | None = None,
        cache_control: str = "no-store",
        etag: str | None = None,
        extra_headers: dict | None = None,
    ):
        """Write security, CORS, caching, and rate-limit headers."""
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Strict-Transport-Security", "max-age=63072000; includeSubDomains; preload")

        # CORS headers
        allowed_origin, is_wildcard = self._get_allowed_origin()
        if allowed_origin:
            self.send_header("Access-Control-Allow-Origin", allowed_origin)
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Authorization, X-API-Key, Content-Type, If-None-Match")
        self.send_header("Access-Control-Expose-Headers", "X-RateLimit-Limit, X-RateLimit-Remaining, X-RateLimit-Reset, Retry-After, ETag, X-Request-Id")
        self.send_header("Access-Control-Max-Age", "86400")

        vary_parts = ["Authorization", "X-API-Key"]
        if not is_wildcard:
            vary_parts.append("Origin")
        self.send_header("Vary", ", ".join(vary_parts))

        # Cache-Control & ETag
        self.send_header("Cache-Control", cache_control)
        if etag:
            self.send_header("ETag", etag)

        # Rate-limit headers
        if rate_info:
            self.send_header("X-RateLimit-Limit", str(rate_info["limit"]))
            self.send_header("X-RateLimit-Remaining", str(max(0, rate_info["remaining"])))
            self.send_header("X-RateLimit-Reset", str(rate_info["reset"]))
            if rate_info.get("retry_after") is not None:
                self.send_header("Retry-After", str(rate_info["retry_after"]))

        if extra_headers:
            for k, v in extra_headers.items():
                self.send_header(k, v)

    def _send_json(
        self,
        status_code: int,
        payload: dict,
        rate_info: dict | None = None,
        cache_control: str = "no-store",
        etag: str | None = None,
        extra_headers: dict | None = None,
    ):
        body = json.dumps(payload, default=_json_default, separators=(",", ":")).encode("utf-8")
        self.send_response(status_code)
        self._send_standard_headers(
            rate_info=rate_info,
            cache_control=cache_control,
            etag=etag,
            extra_headers=extra_headers,
        )
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # ─── Authentication ──────────────────────────────────────────────

    def _authenticate(self, query_params: dict) -> tuple[bool, str | None, str | None, int]:
        """
        Validate API key using constant-time hmac.compare_digest.
        Supports key rotation via comma-separated keys in ANALYTICS_API_KEY.
        Explicitly rejects API keys passed in URL query parameters.

        Returns: (is_valid, matched_key_fingerprint, error_message, status_code)
        """
        # Reject query-string tokens to prevent credential leakage in logs/referrers
        if any(k in query_params for k in ("api_key", "key", "token", "access_token")):
            return (
                False,
                None,
                "Passing API keys in URL query parameters is forbidden. Use 'Authorization: Bearer <key>' or 'X-API-Key: <key>' header.",
                400,
            )

        raw_configured = os.environ.get("ANALYTICS_API_KEY", "").strip()
        if not raw_configured:
            # Fail-closed when environment variable is not configured
            return False, None, "API authentication is not configured on the server.", 503

        valid_keys = [k.strip() for k in raw_configured.split(",") if k.strip()]
        if not valid_keys:
            return False, None, "API authentication is not configured on the server.", 503

        # Extract candidate token from Authorization: Bearer <token> or X-API-Key
        candidate = None
        auth_header = (self.headers.get("Authorization") or "").strip()
        if auth_header:
            parts = auth_header.split(" ", 1)
            if len(parts) == 2 and parts[0].lower() == "bearer":
                candidate = parts[1].strip()
            else:
                return False, None, "Malformed Authorization header. Expected 'Authorization: Bearer <token>'.", 401
        else:
            x_api_key = (self.headers.get("X-API-Key") or "").strip()
            if x_api_key:
                candidate = x_api_key

        if not candidate:
            return False, None, "Missing API key. Provide 'Authorization: Bearer <token>' or 'X-API-Key' header.", 401

        candidate_bytes = candidate.encode("utf-8")
        matched = False
        for expected in valid_keys:
            if hmac.compare_digest(candidate_bytes, expected.encode("utf-8")):
                matched = True

        if not matched:
            return False, None, "Invalid API key.", 401

        key_fp = hashlib.sha256(candidate_bytes).hexdigest()[:16]
        return True, key_fp, None, 200

    # ─── Database & Rate Limiting ────────────────────────────────────

    def _get_db_connection(self):
        db_port_str = os.environ.get("DB_PORT", "3306")
        try:
            db_port = int(db_port_str)
        except ValueError:
            db_port = 3306

        return pymysql.connect(
            host=os.environ.get("DB_HOST", ""),
            port=db_port,
            user=os.environ.get("DB_USER", ""),
            password=os.environ.get("DB_PASSWORD", ""),
            database=os.environ.get("DB_NAME", ""),
            cursorclass=pymysql.cursors.DictCursor,
            connect_timeout=5,
            read_timeout=10,
            write_timeout=10,
            charset="utf8mb4",
        )

    def _get_client_ip(self) -> str:
        """Extract client IP from Vercel proxy headers."""
        xff = self.headers.get("X-Forwarded-For")
        if xff:
            return xff.split(",")[0].strip()
        return (self.headers.get("X-Real-IP") or self.client_address[0] or "unknown").strip()

    def _check_rate_limit(self, connection, key_fingerprint: str) -> tuple[bool, dict]:
        """
        Enforce fixed-window rate limit using a single atomic MySQL upsert.
        Stores at most 1 row per (key_fingerprint, client_ip) pair.
        """
        try:
            limit = max(1, int(os.environ.get("ANALYTICS_RATE_LIMIT", str(DEFAULT_RATE_LIMIT))))
        except ValueError:
            limit = DEFAULT_RATE_LIMIT

        try:
            window_sec = max(1, int(os.environ.get("ANALYTICS_RATE_WINDOW", str(DEFAULT_RATE_WINDOW))))
        except ValueError:
            window_sec = DEFAULT_RATE_WINDOW

        now_ts = int(time.time())
        current_window = (now_ts // window_sec) * window_sec
        reset_ts = current_window + window_sec

        client_ip = self._get_client_ip()
        rate_key = hashlib.sha256(f"{key_fingerprint}:{client_ip}".encode("utf-8")).hexdigest()[:64]

        with connection.cursor() as cursor:
            # Self-healing table creation if bot hasn't migrated yet
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS api_rate_limits (
                    rate_key VARCHAR(128) PRIMARY KEY,
                    window_start BIGINT NOT NULL,
                    request_count INT NOT NULL DEFAULT 1,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
                )
            ''')
            cursor.execute(
                '''
                INSERT INTO api_rate_limits (rate_key, window_start, request_count)
                VALUES (%s, %s, 1)
                ON DUPLICATE KEY UPDATE
                    request_count = IF(window_start = VALUES(window_start), request_count + 1, 1),
                    window_start = VALUES(window_start)
                ''',
                (rate_key, current_window),
            )
            cursor.execute(
                "SELECT request_count FROM api_rate_limits WHERE rate_key = %s",
                (rate_key,),
            )
            row = cursor.fetchone()
        connection.commit()

        count = int(row["request_count"]) if row else 1
        allowed = count <= limit
        remaining = max(0, limit - count)
        rate_info = {
            "limit": limit,
            "remaining": remaining,
            "reset": reset_ts,
            "retry_after": (reset_ts - now_ts) if not allowed else None,
        }
        return allowed, rate_info

    # ─── Query Parameter Parsing & Validation ────────────────────────

    def _parse_params(self, query_params: dict) -> dict:
        """Parse and validate query parameters with strict bounds checking."""
        now_pht = datetime.now(PHT).date()

        # 1. Sections (?include=rollups,kpi,rankings,live or ?include=all)
        raw_include = query_params.get("include", [None])[0]
        if not raw_include:
            sections = set(DEFAULT_SECTIONS)
        else:
            requested = {s.strip().lower() for s in raw_include.split(",") if s.strip()}
            if "all" in requested:
                sections = set(VALID_SECTIONS)
            else:
                invalid = requested - VALID_SECTIONS
                if invalid:
                    raise ApiValidationError(
                        f"Invalid 'include' section(s): {', '.join(sorted(invalid))}. "
                        f"Allowed values: {', '.join(sorted(VALID_SECTIONS))}, all."
                    )
                sections = requested or set(DEFAULT_SECTIONS)

        # 2. Date window (?start_date=YYYY-MM-DD&end_date=YYYY-MM-DD or ?days=N)
        raw_days = query_params.get("days", [None])[0]
        raw_start = query_params.get("start_date", [None])[0]
        raw_end = query_params.get("end_date", [None])[0]

        if raw_start or raw_end:
            try:
                end_dt = (
                    datetime.strptime(raw_end, "%Y-%m-%d").date()
                    if raw_end and _DATE_RE.fullmatch(raw_end)
                    else now_pht
                )
                if raw_end and not _DATE_RE.fullmatch(raw_end):
                    raise ValueError
            except ValueError:
                raise ApiValidationError("Invalid 'end_date'. Expected format: YYYY-MM-DD.")

            try:
                start_dt = (
                    datetime.strptime(raw_start, "%Y-%m-%d").date()
                    if raw_start and _DATE_RE.fullmatch(raw_start)
                    else (end_dt - timedelta(days=DEFAULT_DAYS - 1))
                )
                if raw_start and not _DATE_RE.fullmatch(raw_start):
                    raise ValueError
            except ValueError:
                raise ApiValidationError("Invalid 'start_date'. Expected format: YYYY-MM-DD.")

            if start_dt > end_dt:
                raise ApiValidationError("'start_date' cannot be after 'end_date'.")

            span_days = (end_dt - start_dt).days + 1
            if span_days > MAX_DAYS:
                raise ApiValidationError(f"Date range cannot exceed {MAX_DAYS} days (requested {span_days} days).")
            days = span_days
        else:
            if raw_days is not None:
                try:
                    days = int(raw_days)
                except ValueError:
                    raise ApiValidationError("Parameter 'days' must be an integer between 1 and 365.")
                if days < 1 or days > MAX_DAYS:
                    raise ApiValidationError(f"Parameter 'days' must be between 1 and {MAX_DAYS}.")
            else:
                days = DEFAULT_DAYS
            end_dt = now_pht
            start_dt = end_dt - timedelta(days=days - 1)

        # 3. Granular JSON inclusion toggle (?include_granular=true|false)
        raw_granular = (query_params.get("include_granular", ["true"])[0] or "true").strip().lower()
        if raw_granular not in ("true", "false", "1", "0"):
            raise ApiValidationError("Parameter 'include_granular' must be 'true' or 'false'.")
        include_granular = raw_granular in ("true", "1")

        # 4. Rankings limit (?ranking_limit=5)
        raw_rank_limit = query_params.get("ranking_limit", [None])[0]
        if raw_rank_limit is not None:
            try:
                ranking_limit = int(raw_rank_limit)
            except ValueError:
                raise ApiValidationError(f"Parameter 'ranking_limit' must be an integer between 1 and {MAX_RANKING_LIMIT}.")
            if ranking_limit < 1 or ranking_limit > MAX_RANKING_LIMIT:
                raise ApiValidationError(f"Parameter 'ranking_limit' must be between 1 and {MAX_RANKING_LIMIT}.")
        else:
            ranking_limit = DEFAULT_RANKING_LIMIT

        return {
            "sections": sections,
            "start_date": start_dt.strftime("%Y-%m-%d"),
            "end_date": end_dt.strftime("%Y-%m-%d"),
            "days": days,
            "include_granular": include_granular,
            "ranking_limit": ranking_limit,
        }

    # ─── Data Builders ───────────────────────────────────────────────

    def _load_name_caches(self, cursor) -> tuple[dict, dict]:
        cursor.execute("SELECT user_id, display_name FROM member_names")
        member_cache = {r["user_id"]: r["display_name"] for r in cursor.fetchall()}

        cursor.execute("SELECT channel_id, channel_name FROM channel_names")
        channel_cache = {r["channel_id"]: r["channel_name"] for r in cursor.fetchall()}
        return member_cache, channel_cache

    def _fetch_rollups_and_kpi(
        self,
        cursor,
        start_date: str,
        end_date: str,
        include_granular: bool,
        want_rollups: bool,
        want_kpi: bool,
        member_cache: dict,
        channel_cache: dict,
    ) -> tuple[list | None, dict | None]:
        """Fetch daily rollups within [start_date, end_date] and compute period KPIs."""
        if include_granular and want_rollups:
            cursor.execute(
                '''
                SELECT date, total_messages, unique_messagers, total_voice_minutes,
                       unique_voice_users, new_joins, new_leaves, total_reactions,
                       total_threads, granular_json
                FROM analytics_daily_rollups
                WHERE date BETWEEN %s AND %s
                ORDER BY date ASC
                ''',
                (start_date, end_date),
            )
        else:
            cursor.execute(
                '''
                SELECT date, total_messages, unique_messagers, total_voice_minutes,
                       unique_voice_users, new_joins, new_leaves, total_reactions,
                       total_threads
                FROM analytics_daily_rollups
                WHERE date BETWEEN %s AND %s
                ORDER BY date ASC
                ''',
                (start_date, end_date),
            )

        rows = cursor.fetchall()

        kpi = None
        if want_kpi:
            total_msgs = sum(int(r.get("total_messages") or 0) for r in rows)
            total_voice = sum(int(r.get("total_voice_minutes") or 0) for r in rows)
            total_joins = sum(int(r.get("new_joins") or 0) for r in rows)
            total_leaves = sum(int(r.get("new_leaves") or 0) for r in rows)
            total_reactions = sum(int(r.get("total_reactions") or 0) for r in rows)
            total_threads = sum(int(r.get("total_threads") or 0) for r in rows)
            peak_messagers = max((int(r.get("unique_messagers") or 0) for r in rows), default=0)
            peak_voice = max((int(r.get("unique_voice_users") or 0) for r in rows), default=0)
            days_count = len(rows)

            kpi = {
                "days_with_data": days_count,
                "total_messages": total_msgs,
                "avg_daily_messages": round(total_msgs / days_count, 1) if days_count > 0 else 0.0,
                "peak_daily_messagers": peak_messagers,
                "total_voice_minutes": total_voice,
                "total_voice_hours": round(total_voice / 60.0, 1),
                "peak_daily_voice_users": peak_voice,
                "new_joins": total_joins,
                "new_leaves": total_leaves,
                "net_member_growth": total_joins - total_leaves,
                "total_reactions": total_reactions,
                "total_threads": total_threads,
            }

        if not want_rollups:
            return None, kpi

        formatted_rollups = []
        for row in rows:
            item = {
                "date": str(row["date"]),
                "total_messages": int(row.get("total_messages") or 0),
                "unique_messagers": int(row.get("unique_messagers") or 0),
                "total_voice_minutes": int(row.get("total_voice_minutes") or 0),
                "unique_voice_users": int(row.get("unique_voice_users") or 0),
                "new_joins": int(row.get("new_joins") or 0),
                "new_leaves": int(row.get("new_leaves") or 0),
                "total_reactions": int(row.get("total_reactions") or 0),
                "total_threads": int(row.get("total_threads") or 0),
            }

            if include_granular:
                raw_g = row.get("granular_json")
                if raw_g:
                    try:
                        g = json.loads(raw_g) if isinstance(raw_g, str) else raw_g
                        # Resolve raw snowflake IDs & stringify 64-bit IDs
                        for section_key, id_field in (
                            ("quiz_top_3", "user_id"),
                            ("thanks_top_3", "user_id"),
                            ("top_invites", "inviter"),
                        ):
                            for entry in g.get(section_key, []):
                                uid = entry.get(id_field)
                                if uid is not None:
                                    uid_int = int(uid) if str(uid).isdigit() else uid
                                    if _is_raw_id(entry.get("name")):
                                        resolved = member_cache.get(uid_int)
                                        if resolved:
                                            entry["name"] = resolved
                                    entry[id_field] = _str_id(uid)

                        for section_key in ("top_text_channels", "top_voice_channels"):
                            for entry in g.get(section_key, []):
                                cid = entry.get("channel_id")
                                if cid is not None:
                                    cid_int = int(cid) if str(cid).isdigit() else cid
                                    if _is_raw_id(entry.get("name")):
                                        resolved = channel_cache.get(cid_int)
                                        if resolved:
                                            entry["name"] = resolved
                                    entry["channel_id"] = _str_id(cid)

                        item["granular"] = g
                    except Exception:
                        item["granular"] = {}
                else:
                    item["granular"] = {}

            formatted_rollups.append(item)

        return formatted_rollups, kpi

    def _fetch_rankings(self, cursor, limit: int, member_cache: dict) -> dict:
        """Fetch all-time & weekly rankings, quiz stats, and counting state."""
        # 1. Top Raffles
        cursor.execute(
            '''
            SELECT er.raffle_id, r.title, COUNT(*) AS total_entries
            FROM event_raffle_entries er
            JOIN event_raffles r ON r.id = er.raffle_id
            GROUP BY er.raffle_id, r.title
            ORDER BY total_entries DESC LIMIT %s
            ''',
            (limit,),
        )
        top_raffles = [
            {
                "raffle_id": int(r["raffle_id"]),
                "title": r["title"] or f"Raffle #{r['raffle_id']}",
                "total_entries": int(r["total_entries"] or 0),
            }
            for r in cursor.fetchall()
        ]

        # 2. Top Events
        cursor.execute(
            '''
            SELECT ere.event_id,
                   COALESCE(er.title, CONCAT('Event #', ere.event_id)) AS title,
                   COUNT(*) AS total_participants
            FROM event_registration_entries ere
            LEFT JOIN event_registrations er ON er.event_id = ere.event_id
            GROUP BY ere.event_id, er.title
            ORDER BY total_participants DESC LIMIT %s
            ''',
            (limit,),
        )
        top_events = [
            {
                "event_id": _str_id(r["event_id"]),
                "title": r["title"],
                "total_participants": int(r["total_participants"] or 0),
            }
            for r in cursor.fetchall()
        ]

        # 3. Quiz Speedsters
        cursor.execute(
            '''
            SELECT qal.user_id,
                   COALESCE(mn.display_name, CONCAT('User ', qal.user_id)) AS name,
                   AVG(qal.time_taken) AS avg_time,
                   COUNT(*) AS correct_answers
            FROM quiz_answer_logs qal
            LEFT JOIN member_names mn ON mn.user_id = qal.user_id
            GROUP BY qal.user_id, mn.display_name
            HAVING correct_answers >= 5
            ORDER BY avg_time ASC LIMIT %s
            ''',
            (limit,),
        )
        top_speedsters = [
            {
                "user_id": _str_id(r["user_id"]),
                "name": r["name"],
                "avg_time_seconds": round(float(r["avg_time"] or 0.0), 2),
                "correct_answers": int(r["correct_answers"] or 0),
            }
            for r in cursor.fetchall()
        ]

        # 4. Quiz Streaks
        cursor.execute(
            '''
            SELECT qus.user_id,
                   COALESCE(mn.display_name, CONCAT('User ', qus.user_id)) AS name,
                   qus.current_streak,
                   qus.max_streak
            FROM quiz_user_streaks qus
            LEFT JOIN member_names mn ON mn.user_id = qus.user_id
            ORDER BY qus.max_streak DESC LIMIT %s
            ''',
            (limit,),
        )
        top_streaks = [
            {
                "user_id": _str_id(r["user_id"]),
                "name": r["name"],
                "current_streak": int(r.get("current_streak") or 0),
                "max_streak": int(r.get("max_streak") or 0),
            }
            for r in cursor.fetchall()
        ]

        # 5. Hardest Quiz Questions
        cursor.execute(
            '''
            SELECT question_id, question_text, times_asked, times_correct,
                   (1 - (times_correct / times_asked)) * 100 AS failure_rate
            FROM quiz_question_stats
            WHERE times_asked >= 3
            ORDER BY failure_rate DESC LIMIT %s
            ''',
            (limit,),
        )
        hardest_questions = [
            {
                "question_id": r["question_id"],
                "question_text": r["question_text"],
                "times_asked": int(r.get("times_asked") or 0),
                "times_correct": int(r.get("times_correct") or 0),
                "failure_rate_pct": round(float(r.get("failure_rate") or 0.0), 1),
            }
            for r in cursor.fetchall()
        ]

        # 6. Global Quiz Summary
        cursor.execute("SELECT AVG(time_taken) AS avg_time, COUNT(*) AS total_correct FROM quiz_answer_logs")
        qg = cursor.fetchone() or {}
        quiz_global = {
            "avg_time_seconds": round(float(qg.get("avg_time") or 0.0), 2),
            "total_correct": int(qg.get("total_correct") or 0),
        }

        # 7. Counting Game Summary
        counting_summary = {}
        try:
            cursor.execute("SELECT current_count, high_score, high_score_broken_by FROM counting_state LIMIT 1")
            cs = cursor.fetchone()
            if cs:
                broken_by = cs.get("high_score_broken_by")
                counting_summary = {
                    "current_streak": int(cs.get("current_count") or 0),
                    "high_score": int(cs.get("high_score") or 0),
                    "high_score_broken_by": _str_id(broken_by),
                    "high_score_broken_by_name": member_cache.get(broken_by) if broken_by else None,
                }
        except Exception:
            counting_summary = {}

        return {
            "top_raffles": top_raffles,
            "top_events": top_events,
            "quiz_speedsters": top_speedsters,
            "quiz_streaks": top_streaks,
            "hardest_questions": hardest_questions,
            "quiz_global": quiz_global,
            "counting": counting_summary,
        }

    def _fetch_live_metrics(self, cursor, days: int, member_cache: dict, channel_cache: dict) -> dict:
        """Fetch live raw-table metrics (DAU/WAU/MAU, stickiness, retention, peak hours, top channels, invites)."""
        # 1. Active Users (DAU / WAU / MAU + period-over-period changes)
        cursor.execute('''
            SELECT COUNT(*) AS c FROM (
                SELECT author_id AS uid FROM analytics_messages WHERE created_at >= CURDATE()
                UNION
                SELECT user_id AS uid FROM analytics_voice_sessions WHERE joined_at >= CURDATE()
            ) AS t
        ''')
        dau = int((cursor.fetchone() or {}).get("c") or 0)

        cursor.execute('''
            SELECT COUNT(*) AS c FROM (
                SELECT author_id AS uid FROM analytics_messages WHERE created_at >= DATE_SUB(CURDATE(), INTERVAL 7 DAY)
                UNION
                SELECT user_id AS uid FROM analytics_voice_sessions WHERE joined_at >= DATE_SUB(CURDATE(), INTERVAL 7 DAY)
            ) AS t
        ''')
        wau = int((cursor.fetchone() or {}).get("c") or 0)

        cursor.execute('''
            SELECT COUNT(*) AS c FROM (
                SELECT author_id AS uid FROM analytics_messages WHERE created_at >= DATE_SUB(CURDATE(), INTERVAL 30 DAY)
                UNION
                SELECT user_id AS uid FROM analytics_voice_sessions WHERE joined_at >= DATE_SUB(CURDATE(), INTERVAL 30 DAY)
            ) AS t
        ''')
        mau = int((cursor.fetchone() or {}).get("c") or 0)

        cursor.execute('''
            SELECT COUNT(*) AS c FROM (
                SELECT author_id AS uid FROM analytics_messages
                WHERE created_at >= DATE_SUB(CURDATE(), INTERVAL 14 DAY)
                  AND created_at < DATE_SUB(CURDATE(), INTERVAL 7 DAY)
                UNION
                SELECT user_id AS uid FROM analytics_voice_sessions
                WHERE joined_at >= DATE_SUB(CURDATE(), INTERVAL 14 DAY)
                  AND joined_at < DATE_SUB(CURDATE(), INTERVAL 7 DAY)
            ) AS t
        ''')
        prev_wau = int((cursor.fetchone() or {}).get("c") or 0)

        cursor.execute('''
            SELECT COUNT(*) AS c FROM (
                SELECT author_id AS uid FROM analytics_messages
                WHERE created_at >= DATE_SUB(CURDATE(), INTERVAL 60 DAY)
                  AND created_at < DATE_SUB(CURDATE(), INTERVAL 30 DAY)
                UNION
                SELECT user_id AS uid FROM analytics_voice_sessions
                WHERE joined_at >= DATE_SUB(CURDATE(), INTERVAL 60 DAY)
                  AND joined_at < DATE_SUB(CURDATE(), INTERVAL 30 DAY)
            ) AS t
        ''')
        prev_mau = int((cursor.fetchone() or {}).get("c") or 0)

        def _pct(curr: int, prev: int) -> float | None:
            return round((curr - prev) / prev * 100.0, 1) if prev > 0 else None

        stickiness = round(dau / wau * 100.0, 1) if wau > 0 else 0.0

        # 2. Retention (Day-1 and Day-7)
        now_pht = datetime.now(PHT)
        retention = {}
        for day_n in (1, 7):
            target_date = (now_pht - timedelta(days=day_n)).strftime("%Y-%m-%d")
            cursor.execute(
                "SELECT COUNT(*) AS c FROM analytics_member_joins WHERE DATE(joined_at) = %s",
                (target_date,),
            )
            joined_c = int((cursor.fetchone() or {}).get("c") or 0)

            cursor.execute(
                '''
                SELECT COUNT(DISTINCT am.author_id) AS c
                FROM analytics_messages am
                INNER JOIN analytics_member_joins amj ON am.author_id = amj.user_id
                WHERE DATE(amj.joined_at) = %s AND am.created_at > amj.joined_at
                ''',
                (target_date,),
            )
            retained_c = int((cursor.fetchone() or {}).get("c") or 0)
            retention[f"day_{day_n}"] = {
                "cohort_date": target_date,
                "joined": joined_c,
                "retained": retained_c,
                "rate_pct": round(retained_c / joined_c * 100.0, 1) if joined_c > 0 else 0.0,
            }

        # 3. Peak Hours Heatmap Matrix (Mon=0 .. Sun=6, Hours 0..23) over requested `days` window (capped at 30d raw retention)
        raw_window_days = min(days, 30)
        cursor.execute(
            '''
            SELECT hour_of_day, day_of_week, COUNT(*) AS msg_count
            FROM analytics_messages
            WHERE created_at >= DATE_SUB(NOW(), INTERVAL %s DAY)
            GROUP BY hour_of_day, day_of_week
            ''',
            (raw_window_days,),
        )
        grid = [[0 for _ in range(24)] for _ in range(7)]
        for r in cursor.fetchall():
            if r["day_of_week"] is not None and r["hour_of_day"] is not None:
                d_idx = (int(r["day_of_week"]) + 5) % 7
                h_idx = int(r["hour_of_day"])
                if 0 <= d_idx < 7 and 0 <= h_idx < 24:
                    grid[d_idx][h_idx] = int(r["msg_count"] or 0)

        day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        peak_hours = {day_names[i]: grid[i] for i in range(7)}

        # 4. Top Text Channels in Live Window
        cursor.execute(
            '''
            SELECT channel_id, COUNT(*) AS msg_count, COUNT(DISTINCT author_id) AS unique_authors
            FROM analytics_messages
            WHERE created_at >= DATE_SUB(NOW(), INTERVAL %s DAY)
            GROUP BY channel_id
            ORDER BY msg_count DESC LIMIT 10
            ''',
            (raw_window_days,),
        )
        top_text_channels = [
            {
                "channel_id": _str_id(r["channel_id"]),
                "name": channel_cache.get(r["channel_id"], str(r["channel_id"])),
                "message_count": int(r["msg_count"] or 0),
                "unique_authors": int(r["unique_authors"] or 0),
            }
            for r in cursor.fetchall()
        ]

        # 5. Top Voice Channels in Live Window
        cursor.execute(
            '''
            SELECT channel_id,
                   COALESCE(ROUND(SUM(TIMESTAMPDIFF(MINUTE, joined_at, COALESCE(left_at, NOW())))), 0) AS total_minutes,
                   COUNT(DISTINCT user_id) AS unique_users
            FROM analytics_voice_sessions
            WHERE joined_at >= DATE_SUB(NOW(), INTERVAL %s DAY)
            GROUP BY channel_id
            ORDER BY total_minutes DESC LIMIT 10
            ''',
            (days,),
        )
        top_voice_channels = [
            {
                "channel_id": _str_id(r["channel_id"]),
                "name": channel_cache.get(r["channel_id"], str(r["channel_id"])),
                "total_minutes": int(r["total_minutes"] or 0),
                "unique_users": int(r["unique_users"] or 0),
            }
            for r in cursor.fetchall()
        ]

        # 6. Top Invite Attribution
        cursor.execute(
            '''
            SELECT invite_code, inviter_id, COUNT(*) AS join_count
            FROM analytics_member_joins
            WHERE invite_code IS NOT NULL AND joined_at >= DATE_SUB(NOW(), INTERVAL %s DAY)
            GROUP BY invite_code, inviter_id
            ORDER BY join_count DESC LIMIT 10
            ''',
            (days,),
        )
        top_invites = [
            {
                "invite_code": r["invite_code"],
                "inviter_id": _str_id(r["inviter_id"]),
                "inviter_name": member_cache.get(r["inviter_id"], str(r["inviter_id"])) if r["inviter_id"] else None,
                "joins": int(r["join_count"] or 0),
            }
            for r in cursor.fetchall()
        ]

        return {
            "window_days": days,
            "raw_message_window_days": raw_window_days,
            "active_users": {
                "dau": dau,
                "wau": wau,
                "mau": mau,
                "wau_change_pct": _pct(wau, prev_wau),
                "mau_change_pct": _pct(mau, prev_mau),
                "stickiness_pct": stickiness,
            },
            "retention": retention,
            "peak_hours_heatmap": peak_hours,
            "top_text_channels": top_text_channels,
            "top_voice_channels": top_voice_channels,
            "top_invites": top_invites,
        }

    # ─── HTTP Verb Handlers ──────────────────────────────────────────

    def do_OPTIONS(self):
        """Handle CORS preflight requests."""
        self.send_response(204)
        self._send_standard_headers(cache_control="public, max-age=86400")
        self.end_headers()

    def do_GET(self):
        request_id = str(uuid.uuid4())
        parsed_url = urlparse(self.path)
        query_params = parse_qs(parsed_url.query, keep_blank_values=True)

        # 1. Authenticate Request
        is_authed, key_fp, auth_err, auth_status = self._authenticate(query_params)
        if not is_authed:
            extra = {"WWW-Authenticate": 'Bearer realm="analytics"'} if auth_status == 401 else None
            self._send_json(
                auth_status,
                {
                    "success": False,
                    "error": {
                        "code": "UNAUTHORIZED" if auth_status == 401 else "AUTH_ERROR",
                        "message": auth_err,
                    },
                    "meta": {"request_id": request_id},
                },
                extra_headers=extra,
            )
            return

        # 2. Validate Query Parameters before opening DB connection
        try:
            params = self._parse_params(query_params)
        except ApiValidationError as ve:
            self._send_json(
                400,
                {
                    "success": False,
                    "error": {
                        "code": "INVALID_PARAMETERS",
                        "message": str(ve),
                    },
                    "meta": {"request_id": request_id},
                },
            )
            return

        # 3. Connect to Database & Enforce Rate Limit
        connection = None
        rate_info = None
        try:
            connection = self._get_db_connection()
            allowed, rate_info = self._check_rate_limit(connection, key_fp)
            if not allowed:
                self._send_json(
                    429,
                    {
                        "success": False,
                        "error": {
                            "code": "RATE_LIMIT_EXCEEDED",
                            "message": f"Rate limit of {rate_info['limit']} requests per window exceeded. Retry after {rate_info['retry_after']}s.",
                        },
                        "meta": {"request_id": request_id},
                    },
                    rate_info=rate_info,
                )
                return

            # 4. Execute Requested Queries
            sections = params["sections"]
            data_payload = {}

            with connection.cursor() as cursor:
                need_caches = (
                    ("rollups" in sections and params["include_granular"])
                    or "rankings" in sections
                    or "live" in sections
                )
                if need_caches:
                    member_cache, channel_cache = self._load_name_caches(cursor)
                else:
                    member_cache, channel_cache = {}, {}

                if "rollups" in sections or "kpi" in sections:
                    rollups_data, kpi_data = self._fetch_rollups_and_kpi(
                        cursor=cursor,
                        start_date=params["start_date"],
                        end_date=params["end_date"],
                        include_granular=params["include_granular"],
                        want_rollups="rollups" in sections,
                        want_kpi="kpi" in sections,
                        member_cache=member_cache,
                        channel_cache=channel_cache,
                    )
                    if "kpi" in sections:
                        data_payload["kpi"] = kpi_data
                    if "rollups" in sections:
                        data_payload["rollups"] = rollups_data

                if "rankings" in sections:
                    data_payload["rankings"] = self._fetch_rankings(
                        cursor=cursor,
                        limit=params["ranking_limit"],
                        member_cache=member_cache,
                    )

                if "live" in sections:
                    data_payload["live"] = self._fetch_live_metrics(
                        cursor=cursor,
                        days=params["days"],
                        member_cache=member_cache,
                        channel_cache=channel_cache,
                    )

            response_obj = {
                "success": True,
                "meta": {
                    "request_id": request_id,
                    "generated_at": datetime.now(PHT).isoformat(),
                    "timezone": "Asia/Manila (UTC+8)",
                    "filters": {
                        "include": sorted(sections),
                        "start_date": params["start_date"],
                        "end_date": params["end_date"],
                        "days": params["days"],
                        "include_granular": params["include_granular"],
                        "ranking_limit": params["ranking_limit"],
                    },
                },
                "data": data_payload,
            }

            # 5. Compute ETag & Handle Conditional GET (If-None-Match -> 304)
            deterministic_bytes = json.dumps(
                data_payload, default=_json_default, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
            etag = f'W/"{hashlib.sha256(deterministic_bytes).hexdigest()[:24]}"'

            # Edge cache configuration:
            # Since Authorization header is present, Vercel CDN respects s-maxage whenVary/Cache-Control is set
            cache_header = "public, max-age=60, s-maxage=300, stale-while-revalidate=600"

            client_etag = (self.headers.get("If-None-Match") or "").strip()
            if client_etag and client_etag == etag:
                self.send_response(304)
                self._send_standard_headers(
                    rate_info=rate_info,
                    cache_control=cache_header,
                    etag=etag,
                    extra_headers={"X-Request-Id": request_id},
                )
                self.end_headers()
                return

            self._send_json(
                200,
                response_obj,
                rate_info=rate_info,
                cache_control=cache_header,
                etag=etag,
                extra_headers={"X-Request-Id": request_id},
            )

        except pymysql.MySQLError as dbe:
            print(f"[api/analytics] [{request_id}] Database error: {dbe}", file=sys.stderr)
            self._send_json(
                503,
                {
                    "success": False,
                    "error": {
                        "code": "DATABASE_UNAVAILABLE",
                        "message": "Database temporarily unavailable when processing analytics request.",
                    },
                    "meta": {"request_id": request_id},
                },
                rate_info=rate_info,
            )
        except Exception as e:
            print(f"[api/analytics] [{request_id}] Internal error: {e}", file=sys.stderr)
            self._send_json(
                500,
                {
                    "success": False,
                    "error": {
                        "code": "INTERNAL_SERVER_ERROR",
                        "message": "An unexpected internal error occurred.",
                    },
                    "meta": {"request_id": request_id},
                },
                rate_info=rate_info,
            )
        finally:
            if connection is not None:
                try:
                    connection.close()
                except Exception:
                    pass

    # ─── Reject Disallowed HTTP Methods ──────────────────────────────

    def _reject_method(self):
        self._send_json(
            405,
            {
                "success": False,
                "error": {
                    "code": "METHOD_NOT_ALLOWED",
                    "message": f"Method '{self.command}' is not allowed on this endpoint. Use GET.",
                },
            },
            extra_headers={"Allow": "GET, OPTIONS"},
        )

    def do_POST(self):
        self._reject_method()

    def do_PUT(self):
        self._reject_method()

    def do_DELETE(self):
        self._reject_method()

    def do_PATCH(self):
        self._reject_method()
