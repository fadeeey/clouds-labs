"""Wait for an exact HTTP response, including expected error responses."""
import argparse
import json
import time
import urllib.error
import urllib.request

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("url")
parser.add_argument("status", type=int)
parser.add_argument("--timeout", type=float, default=90)
parser.add_argument("--release-marker")
args = parser.parse_args()
deadline = time.monotonic() + args.timeout
last = "no response"
while time.monotonic() < deadline:
    try:
        try:
            response = urllib.request.urlopen(args.url, timeout=min(2, max(.1, deadline - time.monotonic())))
        except urllib.error.HTTPError as error:
            response = error  # A real 503 is the expected result for the broken fixture.
        with response:
            status = response.code
            marker = response.headers.get("X-Lab-Release")
            last = f"HTTP {status}, release marker={marker!r}"
            if status == args.status and (args.release_marker is None or marker == args.release_marker):
                print(json.dumps({"url": args.url, "status": status, "release_marker": marker}))
                break
    except (OSError, urllib.error.URLError) as error:
        last = f"{type(error).__name__}: {error}"
    time.sleep(min(.5, max(0, deadline - time.monotonic())))
else:
    raise SystemExit(f"Deadline exceeded waiting for HTTP {args.status}: {last}")
