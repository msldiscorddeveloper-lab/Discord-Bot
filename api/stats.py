"""
Vercel Serverless Function: /api/stats
Serves analytics dashboard data with server-side name resolution.
"""

from http.server import BaseHTTPRequestHandler
import json
import pymysql
import pymysql.cursors
import os
import re


def _is_raw_id(name):
    """Check if a 'name' field is still a raw Discord snowflake ID."""
    if name is None:
        return True
    return bool(re.fullmatch(r'\d{17,20}', str(name)))


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        # Configure Headers & CORS
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()

        try:
            # Secure connection via Vercel Environment Variables
            db_port = os.environ.get('DB_PORT', '3306')
            try:
                db_port_int = int(db_port)
            except ValueError:
                db_port_int = 3306

            connection = pymysql.connect(
                host=os.environ.get('DB_HOST', ''),
                port=db_port_int,
                user=os.environ.get('DB_USER', ''),
                password=os.environ.get('DB_PASSWORD', ''),
                database=os.environ.get('DB_NAME', ''),
                cursorclass=pymysql.cursors.DictCursor
            )

            with connection.cursor() as cursor:
                # Fetch last 365 days of rollups securely
                cursor.execute("SELECT * FROM analytics_daily_rollups ORDER BY date DESC LIMIT 365")
                rows = cursor.fetchall()

                # Load name caches for live resolution of any remaining raw IDs
                cursor.execute("SELECT user_id, display_name FROM member_names")
                member_cache = {r['user_id']: r['display_name'] for r in cursor.fetchall()}

                cursor.execute("SELECT channel_id, channel_name FROM channel_names")
                channel_cache = {r['channel_id']: r['channel_name'] for r in cursor.fetchall()}

                # Query live member counts from server_settings & verified_users
                cursor.execute(
                    "SELECT `key`, value FROM server_settings WHERE `key` IN ('guild_member_count', 'guild_human_count')"
                )
                settings_map = {r['key']: r['value'] for r in cursor.fetchall()}
                try:
                    total_members = int(settings_map.get('guild_member_count', 0) or 0)
                except ValueError:
                    total_members = 0

                try:
                    human_members = int(settings_map.get('guild_human_count', 0) or 0)
                except ValueError:
                    human_members = 0

                cursor.execute("SELECT COUNT(*) AS c FROM verified_users")
                v_row = cursor.fetchone()
                verified_members = int(v_row['c'] or 0) if v_row else 0

                if total_members <= 0:
                    fallback_count = len(member_cache)
                    total_members = fallback_count
                    human_members = fallback_count

                member_counts = {
                    "total_members": total_members,
                    "human_members": human_members,
                    "verified_members": verified_members,
                    "unverified_human_members": max(0, human_members - verified_members),
                    "verification_rate_pct": round(verified_members / human_members * 100.0, 1) if human_members > 0 else 0.0,
                }

            connection.close()

            # Format types for JSON serialization + resolve names
            for row in rows:
                if 'date' in row and row['date']:
                    row['date'] = str(row['date'])
                if 'granular_json' in row and row['granular_json']:
                    try:
                        g = json.loads(row['granular_json'])

                        # Resolve any remaining raw ID names using cache
                        for section_key, id_field in [('quiz_top_3', 'user_id'), ('thanks_top_3', 'user_id'), ('top_invites', 'inviter')]:
                            for entry in g.get(section_key, []):
                                uid = entry.get(id_field)
                                if uid and _is_raw_id(entry.get('name')):
                                    resolved = member_cache.get(uid)
                                    if resolved:
                                        entry['name'] = resolved

                        for section_key in ['top_text_channels', 'top_voice_channels']:
                            for entry in g.get(section_key, []):
                                cid = entry.get('channel_id')
                                if cid and _is_raw_id(entry.get('name')):
                                    resolved = channel_cache.get(cid)
                                    if resolved:
                                        entry['name'] = resolved

                        row['granular_json'] = g
                    except Exception:
                        row['granular_json'] = {}

            response = {"success": True, "data": rows, "member_counts": member_counts}
            self.wfile.write(json.dumps(response, default=str).encode('utf-8'))

        except Exception as e:
            error_response = {"success": False, "error": str(e)}
            self.wfile.write(json.dumps(error_response).encode('utf-8'))
