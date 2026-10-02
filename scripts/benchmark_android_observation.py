"""Compare read-only observation latency on the same foreground Android screen.

Run as: python -m scripts.benchmark_android_observation --serial SERIAL
Does not launch apps, tap controls, type text, save screenshots, or call a model.
"""
import argparse
import json
import statistics
import time
from pathlib import Path

from jev_mobile.appium_device import AppiumAndroidDevice
from jev_mobile.device import AndroidDevice


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serial', required=True)
    parser.add_argument('--samples', type=int, default=5)
    parser.add_argument('--appium-url', default='http://127.0.0.1:4723')
    parser.add_argument('--idle-timeout-ms', type=int, default=None)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if not 1 <= args.samples <= 30:
        parser.error('Use 1–30 samples.')
    if args.serial not in AndroidDevice.connected():
        parser.error('Select a connected, authorized device.')
    report = {'serial': args.serial, 'scope': 'Read-only hierarchy observation; ADB batch then Appium batch. No model or action timing.', 'backends': {}}
    for device in (AndroidDevice(args.serial), AppiumAndroidDevice(args.serial, server_url=args.appium_url, idle_timeout_ms=args.idle_timeout_ms)):
        try:
            # Separate Appium cold startup from source retrieval timing.
            if device.backend == 'appium':
                _ = device.driver
            samples = []
            fingerprints = set()
            for _ in range(args.samples):
                started = time.perf_counter()
                screen = device.observe()
                samples.append(round((time.perf_counter() - started) * 1000))
                fingerprints.add(screen.fingerprint)
            report['backends'][device.backend] = {
                'session_start_ms': getattr(device, 'session_start_ms', 0),
                'idle_timeout_ms': getattr(device, 'idle_timeout_ms', None),
                'samples_ms': samples, 'median_ms': round(statistics.median(samples)),
                'min_ms': min(samples), 'max_ms': max(samples),
                'distinct_screens': len(fingerprints), 'last_element_count': len(screen.elements),
                'last_text_length': len(screen.text),
            }
        finally:
            device.close()
    data = json.dumps(report, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(data + '\n')
    print(data)


if __name__ == '__main__':
    main()
