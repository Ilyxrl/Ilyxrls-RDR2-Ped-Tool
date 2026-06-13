# ilyxrl's RDR2 Ped Tool

A standalone tool for Red Dead Redemption 2 modding. It includes a Skeleton Merger and a YMT Clothing Asset Swapper. It has a dark user interface to make character rigging and outfit editing faster.

## Features

### Skeleton Merger

- Scans a donor file and copies missing bones into your base skeleton file.
- Fixes bone numbers and connections so the game does not crash.
- Shows the total bone count of your files automatically.

### YMT Asset Swapper

- Copies clothing items from one specific outfit slot to another.
- Can clear out old clothing pieces from a slot before adding new ones.
- Can replace an entire outfit slot with a new one.
- Includes a search box to find specific items quickly.

## Requirements

- CodeX: You need this tool to extract the raw .yft files from the game to .yft.xml, which the program can actually use.
- No Bone Limit ASI: Otherwise the game can crash when there's a high bone count

## How to Run

### Using the EXE

1. Download the zip file from the Releases section on the right side of the GitHub page.
2. Extract the folder to your computer.
3. Open the folder and double-click Ilyxrls_Ped_Mechanic.exe to run the tool.

### Running from Source Code

If you want to run the raw Python script, open your terminal and install the interface tool first:

```bash
pip install customtkinter
python Ilyxrls_Ped_Mechanic.py
```
