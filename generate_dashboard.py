#!/usr/bin/env python3

import json
from pathlib import Path
import sys

def load_data(path=None):
    if path is None:
        path = "suggested_tasks.txt"
    with open(path, 'r', encoding='utf-8') as file:
        return [line.strip() for line in file.readlines()]

def generate_report(data):
    report_content = "Clear Horizon Tech\n\n"
    for task in data:
        report_content += f"- {task}\n"
    return report_content

def save_report(content, output_path="dashboard_report.md"):
    with open(output_path, 'w', encoding='utf-8') as file:
        file.write(content)

def main():
    data = load_data()
    if not data:
        print("No tasks found in suggested_tasks.txt.", file=sys.stderr)
        return 0

    report_content = generate_report(data)
    save_report(report_content)
    print("Dashboard report generated successfully.", file=sys.stderr)
    return 0

if __name__ == "__main__":
    main()
