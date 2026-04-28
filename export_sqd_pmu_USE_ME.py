#!/usr/bin/env python3
"""
Export a standalone Siemens PMU SeqData .dat file to CSV and open zoomable plots.

This version marks the best respiratory and pulse files with USE_ME,
adds obvious time_seconds and magnitude columns, and plots only those two
channels by default.

Usage:
    python3 export_sqd_pmu_USE_ME.py LeftMiddlePMU.dat

Existing-folder plotting mode:
    python3 export_sqd_pmu_USE_ME.py LeftMiddlePMU_csv

The two recommended scalar waveform CSVs are:
    PMUData_08_RESP_CUSHION_signal_USE_ME.csv
    PMUData_05_PULSE_signal_USE_ME.csv

For quick plotting, use:
    time_seconds as x-axis
    magnitude as y-axis
"""

import argparse
import csv
import math
import struct
import sys
from collections import defaultdict
from pathlib import Path


SIGNAL_NAMES = {
    1: "ECG1",
    2: "ECG2",
    3: "ECG3",
    4: "ECG4",
    5: "PULSE",
    6: "RSP1",
    7: "RSP2",
    8: "RESP_CUSHION",
    9: "EXT_TRIGGER1",
    10: "EXT_TRIGGER2",
    33: "PILOT_TONE_REORDERED",
    34: "PILOT_TONE_HARDWARE",
    35: "PILOT_TONE_CARDIAC",
    36: "PILOT_TONE_RESP",
    49: "EVENT",
}

COMPLEX_SIGNAL_IDS = {33, 34}
EVENT_SIGNAL_IDS = {49}
RESPIRATORY_SIGNAL_IDS = {6, 7, 8, 36}
CARDIAC_SIGNAL_IDS = {1, 2, 3, 4, 5, 35}
USE_ME_SIGNAL_IDS = {5, 8}
DEFAULT_PLOT_SIGNAL_IDS = USE_ME_SIGNAL_IDS
DEFAULT_PLOT_PACKET_LABEL = "PMUData"

PLOT_ORDER = {
    8: 0,
    6: 1,
    7: 2,
    36: 3,
    5: 4,
    1: 5,
    2: 6,
    3: 7,
    4: 8,
    35: 9,
}


class RunningStats:
    def __init__(self):
        self.count = 0
        self.mean = 0.0
        self.m2 = 0.0
        self.minimum = None
        self.maximum = None

    def add(self, value):
        try:
            value = float(value)
        except Exception:
            return

        if not math.isfinite(value):
            return

        self.count += 1

        if self.minimum is None or value < self.minimum:
            self.minimum = value
        if self.maximum is None or value > self.maximum:
            self.maximum = value

        delta = value - self.mean
        self.mean += delta / self.count
        delta2 = value - self.mean
        self.m2 += delta * delta2

    @property
    def std(self):
        if self.count < 2:
            return 0.0
        return math.sqrt(self.m2 / (self.count - 1))


def safe_name(value):
    return "".join(
        character if character.isalnum() or character in "._-" else "_"
        for character in str(value)
    )


def read_string(raw_bytes):
    return raw_bytes.split(b"\x00", 1)[0].decode("latin1", errors="replace")


def parse_scalar_samples(signal_id, size_of_one_sample, payload, number_of_samples):
    if size_of_one_sample <= 0:
        return []

    possible_samples = min(number_of_samples, len(payload) // size_of_one_sample)
    samples = []

    for sample_index in range(possible_samples):
        sample_offset = sample_index * size_of_one_sample

        if signal_id in EVENT_SIGNAL_IDS and size_of_one_sample == 4:
            samples.append(struct.unpack_from("<I", payload, sample_offset)[0])
        elif size_of_one_sample == 4:
            samples.append(struct.unpack_from("<f", payload, sample_offset)[0])
        else:
            samples.append(payload[sample_offset:sample_offset + size_of_one_sample].hex())

    return samples


def parse_complex_samples(size_of_one_sample, payload, number_of_samples):
    if size_of_one_sample <= 0:
        return []

    possible_samples = min(number_of_samples, len(payload) // size_of_one_sample)
    samples = []

    for sample_index in range(possible_samples):
        sample_offset = sample_index * size_of_one_sample

        if size_of_one_sample >= 8:
            real_value, imag_value = struct.unpack_from("<ff", payload, sample_offset)
            samples.append((real_value, imag_value))
        else:
            samples.append(("", ""))

    return samples


def make_writer(output_dir, packet_label, signal_id, signal_name, signal_kind, writers, files):
    file_key = (packet_label, signal_id, signal_name)

    if file_key in writers:
        return writers[file_key], file_key

    if signal_kind == "complex":
        suffix = "complex"
    elif signal_kind == "event":
        suffix = "event"
    elif packet_label == "PMUData" and signal_id in USE_ME_SIGNAL_IDS:
        suffix = "signal_USE_ME"
    else:
        suffix = "signal"

    output_file = output_dir / f"{safe_name(packet_label)}_{signal_id:02d}_{safe_name(signal_name)}_{suffix}.csv"
    handle = output_file.open("w", newline="")
    writer = csv.writer(handle)

    common_columns = [
        "block_index",
        "packet_label",
        "packet_id",
        "packet_timestamp_us",
        "sample_index_in_packet",
        "sample_timestamp_us",
        "seconds_since_first_sample",
        "signal_id",
        "signal_name",
        "sample_period_us",
        "sampling_rate_hz",
    ]

    metadata_columns = [
        "ref_value",
        "normalization_divisor",
        "normalization_offset",
        "version_number",
        "packet_period_us",
        "active_signals",
    ]

    if signal_kind == "complex":
        writer.writerow(
            common_columns
            + [
                "real",
                "imag",
                "magnitude",
            ]
            + metadata_columns
        )
    elif signal_kind == "event":
        writer.writerow(
            common_columns
            + [
                "event_bitmask",
            ]
            + metadata_columns
        )
    else:
        writer.writerow(
            [
                "time_seconds",
                "magnitude",
            ]
            + common_columns
            + [
                "sample_delta",
                "signal_normalized",
                "signal_raw_units",
            ]
            + metadata_columns
        )

    files[file_key] = handle
    writers[file_key] = {
        "writer": writer,
        "path": output_file,
        "kind": signal_kind,
    }

    return writers[file_key], file_key


def should_collect_for_plot(packet_label, signal_id, signal_kind, plot_packet_label, plot_signal_ids):
    if signal_kind != "scalar":
        return False
    if packet_label != plot_packet_label:
        return False
    return signal_id in plot_signal_ids


def parse_and_export(input_path, output_dir=None, plot_packet_label=DEFAULT_PLOT_PACKET_LABEL, plot_signal_ids=None):
    if plot_signal_ids is None:
        plot_signal_ids = DEFAULT_PLOT_SIGNAL_IDS

    if not input_path.exists():
        raise FileNotFoundError(f"File not found: {input_path}")

    data = input_path.read_bytes()

    if output_dir is None:
        output_dir = Path(input_path.with_suffix("").name + "_csv")
    else:
        output_dir = Path(output_dir)
    output_dir.mkdir(exist_ok=True)

    # Remove old recommended filenames from previous versions of this script,
    # so the two preferred files appear only with _USE_ME in their names.
    for stale_name in (
        "PMUData_08_RESP_CUSHION_signal.csv",
        "PMUData_05_PULSE_signal.csv",
    ):
        stale_path = output_dir / stale_name
        if stale_path.exists():
            try:
                stale_path.unlink()
            except OSError:
                pass

    preamble_size = 60
    offset = 0
    block_index = 0

    writers = {}
    files = {}
    first_sample_timestamp_by_channel = {}
    channel_stats = defaultdict(RunningStats)
    channel_counts = defaultdict(int)
    channel_sample_periods = {}
    channel_output_files = {}
    channel_first_time = {}
    channel_last_time = {}
    plot_data = defaultdict(lambda: {"time": [], "signal": [], "stats": RunningStats(), "path": None})

    print("Detected standalone Siemens PMU SeqData-style parser")
    print(f"Input file: {input_path}")
    print(f"Output folder: {output_dir}", flush=True)

    try:
        while offset + preamble_size <= len(data):
            packet_size_from_preamble = int.from_bytes(data[offset:offset + 4], "little")
            packet_label = read_string(data[offset + 4:offset + 54])
            marker = data[offset + 54:offset + 60]

            if marker != b"SQD00\x00":
                if block_index == 0:
                    raise ValueError("This does not look like a standalone Siemens PMU SeqData file; expected SQD00 marker at byte 54.")
                print(f"Stopping at byte {offset}: missing SQD00 marker.")
                break

            packet_start = offset + preamble_size
            packet_end = packet_start + packet_size_from_preamble

            if packet_end > len(data):
                print(f"Stopping at block {block_index}: incomplete final packet.")
                break

            packet = data[packet_start:packet_end]

            if len(packet) < 40:
                print(f"Skipping block {block_index}: packet too short.")
                offset = packet_end
                block_index += 1
                continue

            version_number, extended_packet_header_size, _fill_byte, packet_size = struct.unpack_from("<HBBI", packet, 0)
            packet_timestamp_us = struct.unpack_from("<Q", packet, 8)[0]

            packet_id = ""
            packet_period_us = ""
            active_signals = ""

            if extended_packet_header_size >= 24 and len(packet) >= 40:
                packet_id = struct.unpack_from("<Q", packet, 16)[0]
                packet_period_us = struct.unpack_from("<I", packet, 24)[0]
                active_signals = struct.unpack_from("<Q", packet, 32)[0]

            signal_offset = 16 + extended_packet_header_size

            while signal_offset + 16 <= len(packet):
                (
                    signal_id,
                    size_8byte_align,
                    size_of_one_sample,
                    whole_size_of_signal,
                    number_of_samples,
                    sample_period_us,
                    diff_timestamp_us,
                ) = struct.unpack_from("<BBHHHIi", packet, signal_offset)

                if signal_id == 0 or whole_size_of_signal == 0:
                    break

                if whole_size_of_signal < 40:
                    print(f"Block {block_index}: invalid signal block at packet offset {signal_offset}; stopping this packet.")
                    break

                if signal_offset + whole_size_of_signal > len(packet):
                    print(f"Block {block_index}: signal block overruns packet at packet offset {signal_offset}; stopping this packet.")
                    break

                ref_value, normalization_divisor, normalization_offset = struct.unpack_from("<ddd", packet, signal_offset + 16)

                payload_start = signal_offset + 40
                payload_end = signal_offset + whole_size_of_signal - size_8byte_align
                payload = packet[payload_start:payload_end]

                signal_name = SIGNAL_NAMES.get(signal_id, f"SIGNAL_{signal_id}")

                if signal_id in COMPLEX_SIGNAL_IDS:
                    signal_kind = "complex"
                    samples = parse_complex_samples(size_of_one_sample, payload, number_of_samples)
                elif signal_id in EVENT_SIGNAL_IDS:
                    signal_kind = "event"
                    samples = parse_scalar_samples(signal_id, size_of_one_sample, payload, number_of_samples)
                else:
                    signal_kind = "scalar"
                    samples = parse_scalar_samples(signal_id, size_of_one_sample, payload, number_of_samples)

                writer_info, file_key = make_writer(
                    output_dir,
                    packet_label,
                    signal_id,
                    signal_name,
                    signal_kind,
                    writers,
                    files,
                )
                writer = writer_info["writer"]
                channel_output_files[file_key] = writer_info["path"]

                sampling_rate_hz = ""
                if sample_period_us:
                    sampling_rate_hz = 1_000_000 / sample_period_us

                channel_sample_periods[file_key] = sample_period_us
                collect_plot = should_collect_for_plot(packet_label, signal_id, signal_kind, plot_packet_label, plot_signal_ids)

                for sample_index_in_packet, sample in enumerate(samples):
                    sample_timestamp_us = (
                        packet_timestamp_us
                        + diff_timestamp_us
                        + sample_index_in_packet * sample_period_us
                    )

                    if file_key not in first_sample_timestamp_by_channel:
                        first_sample_timestamp_by_channel[file_key] = sample_timestamp_us

                    seconds_since_first_sample = (
                        sample_timestamp_us - first_sample_timestamp_by_channel[file_key]
                    ) / 1_000_000

                    if file_key not in channel_first_time:
                        channel_first_time[file_key] = seconds_since_first_sample
                    channel_last_time[file_key] = seconds_since_first_sample

                    common_values = [
                        block_index,
                        packet_label,
                        packet_id,
                        packet_timestamp_us,
                        sample_index_in_packet,
                        sample_timestamp_us,
                        f"{seconds_since_first_sample:.6f}",
                        signal_id,
                        signal_name,
                        sample_period_us,
                        f"{sampling_rate_hz:.6f}" if sampling_rate_hz != "" else "",
                    ]

                    metadata_values = [
                        ref_value,
                        normalization_divisor,
                        normalization_offset,
                        version_number,
                        packet_period_us,
                        active_signals,
                    ]

                    if signal_kind == "complex":
                        real_value, imag_value = sample
                        try:
                            magnitude = math.sqrt(real_value * real_value + imag_value * imag_value)
                        except Exception:
                            magnitude = ""
                        writer.writerow(common_values + [real_value, imag_value, magnitude] + metadata_values)
                        if magnitude != "":
                            channel_stats[file_key].add(magnitude)

                    elif signal_kind == "event":
                        event_bitmask = sample
                        writer.writerow(common_values + [event_bitmask] + metadata_values)
                        channel_stats[file_key].add(event_bitmask)

                    else:
                        sample_delta = sample

                        if isinstance(sample_delta, (int, float)):
                            signal_normalized = ref_value + sample_delta
                            signal_raw_units = signal_normalized * normalization_divisor + normalization_offset
                            channel_stats[file_key].add(signal_normalized)
                        else:
                            signal_normalized = ""
                            signal_raw_units = ""

                        writer.writerow(
                            [
                                f"{seconds_since_first_sample:.6f}",
                                signal_normalized,
                            ]
                            + common_values
                            + [
                                sample_delta,
                                signal_normalized,
                                signal_raw_units,
                            ]
                            + metadata_values
                        )

                        if collect_plot and isinstance(signal_normalized, (int, float)):
                            plot_entry = plot_data[file_key]
                            plot_entry["time"].append(seconds_since_first_sample)
                            plot_entry["signal"].append(signal_normalized)
                            plot_entry["stats"].add(signal_normalized)
                            plot_entry["path"] = channel_output_files[file_key]

                    channel_counts[file_key] += 1

                signal_offset += whole_size_of_signal

            offset = packet_end
            block_index += 1

    finally:
        for handle in files.values():
            handle.close()

    print_summary(channel_counts, channel_sample_periods, channel_first_time, channel_last_time, channel_stats, channel_output_files)

    return output_dir, plot_data, channel_stats


def print_summary(channel_counts, channel_sample_periods, channel_first_time, channel_last_time, channel_stats, channel_output_files):
    print("\nWrote CSV files:")
    print("packet_label    id  signal_name                  samples  Hz       duration_s  std         status  file")

    for file_key in sorted(channel_counts.keys()):
        packet_label, signal_id, signal_name = file_key
        count = channel_counts[file_key]
        sample_period_us = channel_sample_periods.get(file_key, "")
        sampling_rate_hz = 1_000_000 / sample_period_us if sample_period_us else 0
        duration_s = channel_last_time.get(file_key, 0) - channel_first_time.get(file_key, 0)
        stats = channel_stats[file_key]

        if stats.count == 0:
            status = "unknown"
            std_text = ""
        elif stats.std < 1e-8:
            status = "flat"
            std_text = f"{stats.std:.3g}"
        else:
            status = "has_variation"
            std_text = f"{stats.std:.3g}"

        print(
            f"{packet_label:14s} {signal_id:02d}  {signal_name:28s} "
            f"{count:8d}  {sampling_rate_hz:7.2f}  {duration_s:10.3f}  "
            f"{std_text:10s}  {status:13s}  {channel_output_files[file_key]}"
        )

    print("\nRecommended USE_ME channels:")
    print("  Respiratory: PMUData_08_RESP_CUSHION_signal_USE_ME.csv")
    print("  Cardiac:     PMUData_05_PULSE_signal_USE_ME.csv")
    print("Use the first two columns for quick plotting:")
    print("  time_seconds = x-axis")
    print("  magnitude    = y-axis")
    print("magnitude is the same corrected waveform as signal_normalized.")


def read_signal_csv(csv_path):
    time_values = []
    signal_values = []
    signal_id = None
    signal_name = csv_path.stem
    packet_label = ""
    sample_rate = ""

    with csv_path.open(newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            return None

        if "time_seconds" in reader.fieldnames:
            time_column = "time_seconds"
        elif "seconds_since_first_sample" in reader.fieldnames:
            time_column = "seconds_since_first_sample"
        else:
            return None

        if "magnitude" in reader.fieldnames:
            signal_column = "magnitude"
        elif "signal_normalized" in reader.fieldnames:
            signal_column = "signal_normalized"
        elif "event_bitmask" in reader.fieldnames:
            signal_column = "event_bitmask"
        else:
            return None

        for row in reader:
            try:
                time_values.append(float(row[time_column]))
                signal_values.append(float(row[signal_column]))
            except Exception:
                continue

            if signal_id is None:
                try:
                    signal_id = int(float(row.get("signal_id", "")))
                except Exception:
                    signal_id = None
                signal_name = row.get("signal_name", signal_name)
                packet_label = row.get("packet_label", packet_label)
                sample_rate = row.get("sampling_rate_hz", sample_rate)

    stats = RunningStats()
    for value in signal_values:
        stats.add(value)

    return {
        "time": time_values,
        "signal": signal_values,
        "signal_id": signal_id,
        "signal_name": signal_name,
        "packet_label": packet_label,
        "sampling_rate_hz": sample_rate,
        "stats": stats,
        "path": csv_path,
    }


def load_plot_data_from_csv_folder(folder, packet_label=DEFAULT_PLOT_PACKET_LABEL, plot_signal_ids=None):
    if plot_signal_ids is None:
        plot_signal_ids = DEFAULT_PLOT_SIGNAL_IDS

    plot_data = {}

    for csv_path in sorted(Path(folder).glob("*_signal*.csv")):
        signal = read_signal_csv(csv_path)
        if signal is None:
            continue
        signal_id = signal["signal_id"]
        if signal["packet_label"] != packet_label:
            continue
        if signal_id not in plot_signal_ids:
            continue

        signal_name = signal["signal_name"]
        key = (signal["packet_label"], signal_id, signal_name)
        plot_data[key] = signal

    return plot_data


def install_zoom_helpers(fig, ax):
    home_xlim = ax.get_xlim()
    home_ylim = ax.get_ylim()

    def on_scroll(event):
        if event.inaxes != ax or event.xdata is None:
            return

        if event.button == "up":
            scale_factor = 0.8
        else:
            scale_factor = 1.25

        if event.key == "shift" and event.ydata is not None:
            current_ylim = ax.get_ylim()
            y_left = event.ydata - (event.ydata - current_ylim[0]) * scale_factor
            y_right = event.ydata + (current_ylim[1] - event.ydata) * scale_factor
            ax.set_ylim(y_left, y_right)
        else:
            current_xlim = ax.get_xlim()
            x_left = event.xdata - (event.xdata - current_xlim[0]) * scale_factor
            x_right = event.xdata + (current_xlim[1] - event.xdata) * scale_factor
            ax.set_xlim(x_left, x_right)

        fig.canvas.draw_idle()

    def on_key(event):
        current_xlim = ax.get_xlim()
        width = current_xlim[1] - current_xlim[0]

        if event.key == "r":
            ax.set_xlim(home_xlim)
            ax.set_ylim(home_ylim)
            fig.canvas.draw_idle()
        elif event.key == "left":
            ax.set_xlim(current_xlim[0] - width * 0.25, current_xlim[1] - width * 0.25)
            fig.canvas.draw_idle()
        elif event.key == "right":
            ax.set_xlim(current_xlim[0] + width * 0.25, current_xlim[1] + width * 0.25)
            fig.canvas.draw_idle()
        elif event.key == "q":
            try:
                import matplotlib.pyplot as plt
                plt.close(fig)
            except Exception:
                pass

    fig.canvas.mpl_connect("scroll_event", on_scroll)
    fig.canvas.mpl_connect("key_press_event", on_key)


def plot_interactive(plot_data, skip_flat=True):
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        print("\nmatplotlib is not installed.")
        print("Install it with: python3 -m pip install matplotlib")
        return

    if not plot_data:
        print("\nNo respiratory/cardiac PMU signals found to plot.")
        return

    sorted_items = sorted(
        plot_data.items(),
        key=lambda item: (PLOT_ORDER.get(item[0][1], 999), item[0][0], item[0][1], item[0][2]),
    )

    opened_any = False
    skipped_flat = []

    for file_key, entry in sorted_items:
        packet_label, signal_id, signal_name = file_key
        time_values = entry.get("time", [])
        signal_values = entry.get("signal", [])
        stats = entry.get("stats", RunningStats())
        path = entry.get("path", "")

        if not time_values or not signal_values:
            continue

        if skip_flat and stats.count > 1 and stats.std < 1e-8:
            skipped_flat.append((packet_label, signal_id, signal_name, path))
            continue

        fig, ax = plt.subplots(figsize=(12, 4))
        ax.plot(time_values, signal_values)
        ax.set_xlabel("Time in seconds")
        ax.set_ylabel("magnitude")
        ax.set_title(f"{packet_label} {signal_id:02d} {signal_name}")
        ax.grid(True)
        try:
            fig.canvas.manager.set_window_title(f"{packet_label}_{signal_id:02d}_{signal_name}")
        except Exception:
            pass
        install_zoom_helpers(fig, ax)
        opened_any = True

    if skipped_flat:
        print("\nSkipped flat channels:")
        for packet_label, signal_id, signal_name, path in skipped_flat:
            print(f"  {packet_label}_{signal_id:02d}_{signal_name}: {path}")

    if not opened_any:
        print("\nNo non-flat respiratory/cardiac channels to plot.")
        return

    print("\nPlot controls:")
    print("  Use the plot window magnifying-glass button to box-zoom.")
    print("  Use the hand button to pan.")
    print("  Mouse wheel zooms the time axis.")
    print("  Shift + mouse wheel zooms the y-axis.")
    print("  Left/right arrow keys pan along time.")
    print("  r resets the view; q closes the active plot window.")

    plt.show()


def parse_signal_ids(text):
    if not text:
        return DEFAULT_PLOT_SIGNAL_IDS

    signal_ids = set()
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        signal_ids.add(int(part))
    return signal_ids


def main():
    parser = argparse.ArgumentParser(
        description="Export standalone Siemens PMU SeqData .dat files to CSV and open zoomable respiratory/cardiac plots."
    )
    parser.add_argument("input", help="PMU .dat file, or an existing *_csv output folder")
    parser.add_argument("--output-dir", default=None, help="Output CSV folder. Default: input filename without extension + _csv")
    parser.add_argument("--no-plot", action="store_true", help="Export CSV only, do not open plots")
    parser.add_argument("--plot-packet-label", default=DEFAULT_PLOT_PACKET_LABEL, help="Packet label to plot. Default: PMUData")
    parser.add_argument(
        "--plot-signal-ids",
        default="",
        help="Comma-separated signal IDs to plot. Default: USE_ME channels only: 5,8",
    )
    parser.add_argument("--show-flat", action="store_true", help="Plot flat/zero channels too")
    args = parser.parse_args()

    input_path = Path(args.input)
    plot_signal_ids = parse_signal_ids(args.plot_signal_ids)

    try:
        if input_path.is_dir():
            output_dir = input_path
            plot_data = load_plot_data_from_csv_folder(
                input_path,
                packet_label=args.plot_packet_label,
                plot_signal_ids=plot_signal_ids,
            )
            print(f"Using existing CSV folder: {output_dir}")
        else:
            output_dir, plot_data, _channel_stats = parse_and_export(
                input_path,
                output_dir=args.output_dir,
                plot_packet_label=args.plot_packet_label,
                plot_signal_ids=plot_signal_ids,
            )

        if not args.no_plot:
            plot_interactive(plot_data, skip_flat=not args.show_flat)

    except Exception as exc:
        print(f"Error: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
