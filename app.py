#!/usr/bin/env python3
"""
app.py -- QuantSuite desktop launcher.

Starts the local pricing server and opens the terminal in the default browser.
This is the entry point that PyInstaller turns into a single double-clickable
executable, so the recipient needs neither Python, Ubuntu, nor ngn/k installed.

The Python engine (engine.py, pure NumPy/SciPy) works on every OS. The native
ngn/k engine is used automatically only when a runnable `k` binary is present
(Linux); otherwise the app silently runs the Python engine — same results.
"""
import os, sys, socket, threading, time, webbrowser

# make server.py importable whether we run from source or from a PyInstaller bundle
sys.path.insert(0, getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__))))
import server


def free_port(preferred=8002):
    """Use the preferred port if free, else let the OS pick one."""
    for p in (preferred, 0):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("", p)); port = s.getsockname()[1]; s.close()
            return port
        except OSError:
            continue
    return preferred


def main():
    port = free_port(int(os.environ.get("PORT", "8002")))
    httpd = server.make_server(port)
    url = "http://localhost:%d/" % port

    banner = ("\n  QuantSuite  ·  Laka Capital\n"
              "  ---------------------------------------------\n"
              "  Server running at:  %s\n"
              "  Python engine: %s     ngn/k engine: %s\n"
              "  Close this window (or press Ctrl+C) to quit.\n" %
              (url, "on" if server.PY_OK else "OFF",
               "on" if server.K_OK else "not available on this OS"))
    print(banner)

    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    time.sleep(0.8)
    try:
        webbrowser.open(url)
    except Exception:
        print("  (could not open a browser automatically — open %s manually)" % url)

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n  Shutting down…")
        httpd.shutdown()


if __name__ == "__main__":
    main()