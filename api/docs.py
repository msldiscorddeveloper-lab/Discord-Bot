"""
Vercel Serverless Function: GET /api/docs
Returns the full API documentation and schema reference for GET /api/analytics.
"""

from http.server import BaseHTTPRequestHandler
import json
import os


API_DOCUMENTATION = {
    "success": True,
    "api": "MLBB Community Bot — External Analytics API",
    "version": "1.0.0",
    "timezone": "Asia/Manila (UTC+8)",
    "endpoints": {
        "/api/analytics": {
            "method": "GET",
            "description": "Retrieve aggregated daily rollups, period KPI summaries, all-time rankings, and live community metrics.",
            "authentication": {
                "required": True,
                "schemes": [
                    {
                        "header": "Authorization",
                        "format": "Bearer <ANALYTICS_API_KEY>",
                        "recommended": True,
                    },
                    {
                        "header": "X-API-Key",
                        "format": "<ANALYTICS_API_KEY>",
                        "recommended": False,
                    },
                ],
                "notes": [
                    "Passing API keys in URL query parameters (?api_key=..., ?token=...) is strictly rejected with 400 Bad Request.",
                    "Supports zero-downtime key rotation via comma-separated keys in the ANALYTICS_API_KEY environment variable.",
                ],
            },
            "rate_limiting": {
                "default_limit": 60,
                "default_window_seconds": 60,
                "scope": "Per (API key + Client IP)",
                "response_headers": {
                    "X-RateLimit-Limit": "Maximum requests permitted in the current window.",
                    "X-RateLimit-Remaining": "Remaining requests permitted in the current window.",
                    "X-RateLimit-Reset": "Unix epoch timestamp (seconds) when the current window resets.",
                    "Retry-After": "Seconds until the client may retry (included on 429 responses).",
                },
            },
            "caching": {
                "cache_control": "public, max-age=60, s-maxage=300, stale-while-revalidate=600",
                "conditional_requests": "Supports weak ETag via 'ETag' response header and 'If-None-Match' request header (returns 304 Not Modified when unchanged).",
            },
            "query_parameters": {
                "include": {
                    "type": "string (comma-separated)",
                    "required": False,
                    "default": "rollups,kpi",
                    "allowed_values": ["rollups", "kpi", "rankings", "live", "all"],
                    "description": "Select which analytics dataset sections to include in 'data'. Pass 'all' to retrieve every section.",
                },
                "days": {
                    "type": "integer",
                    "required": False,
                    "default": 30,
                    "min": 1,
                    "max": 365,
                    "description": "Rolling lookback window in days (aligned to Asia/Manila). Ignored for rollups/kpi if 'start_date' or 'end_date' is provided.",
                },
                "start_date": {
                    "type": "string (YYYY-MM-DD)",
                    "required": False,
                    "default": "end_date - (days - 1)",
                    "description": "Inclusive start date for 'rollups' and 'kpi'. Maximum span between start_date and end_date is 365 days.",
                },
                "end_date": {
                    "type": "string (YYYY-MM-DD)",
                    "required": False,
                    "default": "Current date in Asia/Manila (UTC+8)",
                    "description": "Inclusive end date for 'rollups' and 'kpi'. Must be >= start_date.",
                },
                "include_granular": {
                    "type": "boolean",
                    "required": False,
                    "default": True,
                    "allowed_values": ["true", "false", "1", "0"],
                    "description": "When true, each daily object in 'rollups' includes the nested 'granular' breakdown. Set to false for lightweight time-series payloads.",
                },
                "ranking_limit": {
                    "type": "integer",
                    "required": False,
                    "default": 5,
                    "min": 1,
                    "max": 25,
                    "description": "Maximum number of rows returned per leaderboard inside the 'rankings' section.",
                },
            },
            "response_schema": {
                "meta": {
                    "request_id": "string (UUIDv4)",
                    "generated_at": "string (ISO-8601 timestamp in UTC+8)",
                    "timezone": "Asia/Manila (UTC+8)",
                    "filters": {
                        "include": ["kpi", "rollups"],
                        "start_date": "YYYY-MM-DD",
                        "end_date": "YYYY-MM-DD",
                        "days": 30,
                        "include_granular": True,
                        "ranking_limit": 5,
                    },
                },
                "data": {
                    "kpi": {
                        "description": "Included when 'kpi' or 'all' is in ?include",
                        "fields": {
                            "days_with_data": "int",
                            "total_messages": "int",
                            "avg_daily_messages": "float",
                            "peak_daily_messagers": "int",
                            "total_voice_minutes": "int",
                            "total_voice_hours": "float",
                            "peak_daily_voice_users": "int",
                            "new_joins": "int",
                            "new_leaves": "int",
                            "net_member_growth": "int",
                            "total_reactions": "int",
                            "total_threads": "int",
                            "member_counts": "{total_members: int, human_members: int, verified_members: int, unverified_human_members: int, verification_rate_pct: float}",
                        },
                    },
                    "rollups": {
                        "description": "Included when 'rollups' or 'all' is in ?include. Chronological array of daily records.",
                        "item_fields": {
                            "date": "string (YYYY-MM-DD)",
                            "total_messages": "int",
                            "unique_messagers": "int",
                            "total_voice_minutes": "int",
                            "unique_voice_users": "int",
                            "new_joins": "int",
                            "new_leaves": "int",
                            "total_reactions": "int",
                            "total_threads": "int",
                            "granular": "object (omitted when include_granular=false; contains mod_actions, new_verifications, new_tickets, tickets_by_category, quiz_top_3, thanks_top_3, top_invites, top_text_channels, top_voice_channels, etc.)",
                        },
                    },
                    "rankings": {
                        "description": "Included when 'rankings' or 'all' is in ?include.",
                        "fields": {
                            "top_raffles": "array of {raffle_id: int, title: str, total_entries: int}",
                            "top_events": "array of {event_id: str, title: str, total_participants: int}",
                            "quiz_speedsters": "array of {user_id: str, name: str, avg_time_seconds: float, correct_answers: int}",
                            "quiz_streaks": "array of {user_id: str, name: str, current_streak: int, max_streak: int}",
                            "hardest_questions": "array of {question_id: str, question_text: str, times_asked: int, times_correct: int, failure_rate_pct: float}",
                            "quiz_global": "{avg_time_seconds: float, total_correct: int}",
                            "counting": "{current_streak: int, high_score: int, high_score_broken_by: str|null, high_score_broken_by_name: str|null}",
                        },
                    },
                    "live": {
                        "description": "Included when 'live' or 'all' is in ?include.",
                        "fields": {
                            "window_days": "int",
                            "raw_message_window_days": "int (capped at 30 days raw retention)",
                            "member_counts": "{total_members: int, human_members: int, verified_members: int, unverified_human_members: int, verification_rate_pct: float}",
                            "active_users": "{dau: int, wau: int, mau: int, wau_change_pct: float|null, mau_change_pct: float|null, stickiness_pct: float}",
                            "retention": "{day_1: {cohort_date: str, joined: int, retained: int, rate_pct: float}, day_7: {...}}",
                            "peak_hours_heatmap": "object mapping Monday..Sunday -> array of 24 hourly message counts (00:00..23:00)",
                            "top_text_channels": "array of {channel_id: str, name: str, message_count: int, unique_authors: int}",
                            "top_voice_channels": "array of {channel_id: str, name: str, total_minutes: int, unique_users: int}",
                            "top_invites": "array of {invite_code: str, inviter_id: str|null, inviter_name: str|null, joins: int}",
                        },
                    },
                },
                "notes": [
                    "All 64-bit Discord snowflake IDs (user_id, channel_id, inviter_id, event_id) are serialized as strings to prevent IEEE-754 53-bit integer precision loss in JavaScript clients."
                ],
            },
            "error_codes": {
                "400 INVALID_PARAMETERS": "One or more query parameters failed validation (e.g., invalid date format, range > 365 days, unknown 'include' section, or API key passed in URL).",
                "401 UNAUTHORIZED": "Missing, malformed, or invalid API key.",
                "405 METHOD_NOT_ALLOWED": "HTTP method other than GET or OPTIONS was used.",
                "429 RATE_LIMIT_EXCEEDED": "Client exceeded the configured request quota for the current window.",
                "500 INTERNAL_SERVER_ERROR": "Unexpected server error.",
                "503 AUTH_ERROR / DATABASE_UNAVAILABLE": "ANALYTICS_API_KEY is not configured on the server, or the database is unreachable.",
            },
            "examples": [
                {
                    "description": "Default request (last 30 days of rollups + KPI summary)",
                    "url": "/api/analytics",
                },
                {
                    "description": "Fetch all sections (rollups, KPI, rankings, live metrics) for the last 14 days",
                    "url": "/api/analytics?include=all&days=14",
                },
                {
                    "description": "Custom date range with lightweight rollups (granular breakdown excluded)",
                    "url": "/api/analytics?include=kpi,rollups&start_date=2026-10-01&end_date=2026-10-18&include_granular=false",
                },
                {
                    "description": "Fetch only live metrics and top 10 rankings",
                    "url": "/api/analytics?include=live,rankings&ranking_limit=10&days=7",
                },
            ],
        },
        "/api/docs": {
            "method": "GET",
            "description": "Returns this machine-readable API documentation and parameter specification.",
            "authentication": {
                "required": False,
            },
        },
    },
}


class handler(BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        return

    def _send_headers(self, status_code: int, content_length: int = 0):
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")

        raw_origins = os.environ.get("ANALYTICS_ALLOWED_ORIGINS", "*").strip()
        if not raw_origins or raw_origins == "*":
            self.send_header("Access-Control-Allow-Origin", "*")
        else:
            allowed = {o.strip().rstrip("/") for o in raw_origins.split(",") if o.strip()}
            req_origin = (self.headers.get("Origin") or "").strip().rstrip("/")
            if req_origin and req_origin in allowed:
                self.send_header("Access-Control-Allow-Origin", req_origin)
            self.send_header("Vary", "Origin")

        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Authorization, X-API-Key, Content-Type")
        self.send_header("Cache-Control", "public, max-age=300, s-maxage=3600, stale-while-revalidate=86400")
        if content_length > 0:
            self.send_header("Content-Length", str(content_length))
        self.end_headers()

    def do_OPTIONS(self):
        self._send_headers(204)

    def do_GET(self):
        body = json.dumps(API_DOCUMENTATION, indent=2).encode("utf-8")
        self._send_headers(200, len(body))
        self.wfile.write(body)

    def _reject_method(self):
        body = json.dumps({
            "success": False,
            "error": {
                "code": "METHOD_NOT_ALLOWED",
                "message": f"Method '{self.command}' is not allowed. Use GET.",
            },
        }).encode("utf-8")
        self.send_response(405)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Allow", "GET, OPTIONS")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        self._reject_method()

    def do_PUT(self):
        self._reject_method()

    def do_DELETE(self):
        self._reject_method()

    def do_PATCH(self):
        self._reject_method()
