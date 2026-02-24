import os
import json

def process_suggested_tasks():
    if not os.path.exists("suggested_tasks.txt"):
        print("No suggested_tasks.txt found. Agents can append follow-up task titles there.")
        return

    with open("suggested_tasks.txt", "r") as file:
        tasks = file.readlines()

    for task in tasks:
        task = task.strip()
        if task:
            # Assuming Beads is a function that creates beads
            create_bead(task)
            print(f"Created bead from suggested task: {task}")

def create_bead(task):
    # Placeholder function to simulate creating a bead
    print(f"Creating bead for task: {task}")

if __name__ == "__main__":
    process_suggested_tasks()
