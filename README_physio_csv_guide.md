# Getting physio CSV files from a Siemens scanner PMU `.dat` file

This guide starts from a standalone PMU `.dat` file that was extracted on the scanner, for example:

- input on scanner: `meas_MID00653_FID12571_rest.dat`
- output from scanner extraction: `PMUData.dat`

It then shows how to convert that PMU `.dat` file into CSV files on a local Linux computer using `export_sqd_pmu_USE_ME.py`.

## What this workflow does

1. Extract a standalone PMU `.dat` file on the scanner.
2. Copy that PMU `.dat` file to a local Linux computer.
3. Create a Python virtual environment.
4. Run `export_sqd_pmu_USE_ME.py`.
5. Get CSV files for respiration and pulse.

The two main output files are:

- `PMUData_08_RESP_CUSHION_signal_USE_ME.csv`
- `PMUData_05_PULSE_signal_USE_ME.csv`

For quick plotting and inspection, use:

- `time_seconds` as the x-axis
- `magnitude` as the y-axis

## 1. Extract the PMU `.dat` file on the scanner

Open a command prompt on the scanner and run:

```bash
ehe -extractPMUData -i /Full/Path/To/meas_MID00653_FID12571_rest.dat -o /Full/Path/To/PMUData.dat
```

After this step, you should have a standalone PMU file:

```bash
/Full/Path/To/PMUData.dat
```

## 2. Copy the PMU `.dat` file to your local Linux computer

Copy `PMUData.dat` to your local machine using your normal transfer method.

For example, place it in:

```bash
~/Downloads/PMUData.dat
```

## 3. Put the Python script on your local machine

Save the conversion script as:

```bash
export_sqd_pmu_USE_ME.py
```

Put it in a working folder, for example:

```bash
~/Documents/codes/physio/
```

## 4. Create a Python virtual environment

Open a terminal on the local Linux computer and run:

```bash
sudo apt update
sudo apt install python3 python3-venv python3-pip
```

Create a working folder and move into it:

```bash
mkdir -p ~/Documents/codes/physio
cd ~/Documents/codes/physio
```

Create a virtual environment:

```bash
python3 -m venv ~/physioenv
```

Activate it:

```bash
source ~/physioenv/bin/activate
```

Upgrade `pip` and install plotting support:

```bash
pip install --upgrade pip
pip install matplotlib
```

## 5. Run the converter

With the environment activated, run:

```bash
cd ~/Documents/codes/physio
python3 export_sqd_pmu_USE_ME.py ~/Downloads/PMUData.dat
```

If the input file is named differently, replace `~/Downloads/PMUData.dat` with the correct path.

## 6. Output folder and output files

The script creates an output folder next to the input file name.

Example:

```bash
PMUData_csv/
```

Inside that folder, the main files to use are:

```bash
PMUData_xx_RESP_CUSHION_signal_USE_ME.csv
PMUData_xx_PULSE_signal_USE_ME.csv
```

Other CSV files may also be created for ECG, pilot tone, RSP1, RSP2, and event channels.

## 7. Columns in the two main CSV files

The two easiest columns to use are:

- `time_seconds`
- `magnitude`

Use them as:

- x-axis: `time_seconds`
- y-axis: `magnitude`

The files also contain additional metadata columns. The most useful ones are:

- `seconds_since_first_sample`
- `signal_normalized`
- `signal_raw_units`
- `sample_period_us`
- `sampling_rate_hz`
- `signal_name`

In the `*_USE_ME.csv` files:

- `time_seconds` is the same information as `seconds_since_first_sample`
- `magnitude` is the same information as `signal_normalized`

## 8. Running again later

Whenever you want to use the script again:

```bash
source ~/physioenv/bin/activate
cd ~/Documents/codes/physio
python3 export_sqd_pmu_USE_ME.py /path/to/YourPMUData.dat
```

## 9. Common pattern

Typical session:

```bash
source ~/physioenv/bin/activate
cd ~/Documents/codes/physio
python3 export_sqd_pmu_USE_ME.py ~/Downloads/PMUData.dat
```

Then inspect:

```bash
~/Downloads/PMUData_csv/PMUData_08_RESP_CUSHION_signal_USE_ME.csv
~/Downloads/PMUData_csv/PMUData_05_PULSE_signal_USE_ME.csv
```

## 10. Summary

Use this workflow when you already have a standalone PMU `.dat` file extracted from the scanner.

- scanner step: create `PMUData.dat`
- local step: run `export_sqd_pmu_USE_ME.py`
- main outputs:
  - `PMUData_08_RESP_CUSHION_signal_USE_ME.csv`
  - `PMUData_05_PULSE_signal_USE_ME.csv`
- main columns:
  - `time_seconds`
  - `magnitude`
