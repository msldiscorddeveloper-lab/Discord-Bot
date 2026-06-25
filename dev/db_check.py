"""
Database Connection Checker (for hosted platforms)
Reads DB credentials from environment variables (same ones your bot uses).
Also prints this server's outbound IP so you can whitelist it.
"""

import sys
import os
import socket

try:
    import mysql.connector
    from mysql.connector import Error as MySQLError
except ImportError:
    print("ERROR: mysql-connector-python is not installed.")
    print("Install it with:  pip install mysql-connector-python")
    sys.exit(1)


def get_outbound_ip():
    """Try to detect this server's public IP address."""
    try:
        import urllib.request
        return urllib.request.urlopen("https://api.ipify.org", timeout=5).read().decode()
    except Exception:
        return "Could not detect"


def check_port_reachable(host: str, port: int, timeout: float = 5.0) -> bool:
    """Quick TCP socket check to see if the host:port is reachable."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (socket.timeout, ConnectionRefusedError, OSError):
        return False


def check_database_connection(host: str, port: int, database: str, user: str, password: str) -> None:
    """Attempt a full MySQL connection and report the result."""

    print("=" * 50)
    print("  MySQL / MariaDB Connection Checker")
    print("=" * 50)
    print(f"  Host     : {host}")
    print(f"  Port     : {port}")
    print(f"  Database : {database}")
    print(f"  User     : {user}")
    print(f"  Password : {'*' * len(password)}")
    print("=" * 50)

    # Step 0 — Show this server's IP
    outbound_ip = get_outbound_ip()
    print(f"\n[0/3] This server's outbound IP: {outbound_ip}")
    print(f"      ^ Add this IP to your database's Remote MySQL whitelist!\n")

    # Step 1 — TCP reachability
    print("[1/3] Checking if host:port is reachable …", end=" ")
    if not check_port_reachable(host, port):
        print("FAILED ✗")
        print(f"\n  Could not reach {host}:{port}.")
        print("  Possible causes:")
        print("    • Host is down or does not exist")
        print("    • Port is blocked by a firewall")
        print("    • Incorrect host/port")
        print(f"\n  ➡ FIX: Whitelist this server's IP ({outbound_ip}) in your DB firewall.")
        return
    print("OK ✓")

    # Step 2 — MySQL authentication
    print("[2/3] Authenticating with MySQL server …", end=" ")
    try:
        conn = mysql.connector.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            connection_timeout=10,
        )
    except MySQLError as e:
        print("FAILED ✗")
        print(f"\n  Authentication error: {e}")
        return
    print("OK ✓")

    # Step 3 — Database existence
    print(f"[3/3] Checking if database '{database}' exists …", end=" ")
    try:
        cursor = conn.cursor()
        cursor.execute("SHOW DATABASES")
        databases = [row[0] for row in cursor.fetchall()]
        cursor.close()

        if database in databases:
            print("FOUND ✓")
            print(f"\n  ✅ SUCCESS — The database '{database}' exists and is reachable!")
        else:
            print("NOT FOUND ✗")
            print(f"\n  The database '{database}' does not exist on this server.")
            print(f"  Available databases: {', '.join(databases)}")
    except MySQLError as e:
        print("FAILED ✗")
        print(f"\n  Error querying databases: {e}")
    finally:
        conn.close()


def main():
    # Read from environment variables (same ones your bot uses)
    host = os.getenv("DB_HOST")
    port = os.getenv("DB_PORT", "3306")
    database = os.getenv("DB_NAME")
    user = os.getenv("DB_USER")
    password = os.getenv("DB_PASSWORD")

    missing = []
    if not host: missing.append("DB_HOST")
    if not database: missing.append("DB_NAME")
    if not user: missing.append("DB_USER")
    if not password: missing.append("DB_PASSWORD")

    if missing:
        print(f"ERROR: Missing environment variables: {', '.join(missing)}")
        print("Make sure these are set in your justrunmy.app environment settings.")
        sys.exit(1)

    print(f"Reading DB config from environment variables\n")
    check_database_connection(host, int(port), database, user, password)


if __name__ == "__main__":
    main()
