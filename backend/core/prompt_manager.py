import os
import json
import shutil

BASE_DIR = os.path.dirname(__file__)
PROMPTS_DIR = os.path.join(BASE_DIR, "prompts")
MICRO_PROMPTS_FILE = os.path.join(PROMPTS_DIR, "micro_prompts.json")
DEFAULT_PROMPTS_FILE = os.path.join(PROMPTS_DIR, "micro_prompts.default.json")

class PromptManager:
    def __init__(self):
        self.prompts = {}
        self.default_prompts = {}
        self.load_prompts()

    def load_prompts(self):
        if os.path.exists(DEFAULT_PROMPTS_FILE):
            with open(DEFAULT_PROMPTS_FILE, "r") as f:
                self.default_prompts = json.load(f)
        else:
            raise FileNotFoundError("CRITICAL: micro_prompts.default.json is missing!")

        if not os.path.exists(MICRO_PROMPTS_FILE):
            shutil.copy(DEFAULT_PROMPTS_FILE, MICRO_PROMPTS_FILE)

        try:
            with open(MICRO_PROMPTS_FILE, "r") as f:
                self.prompts = json.load(f)
        except Exception as e:
            print(f"Warning: Could not parse micro_prompts.json ({e}). Falling back to defaults.")
            self.prompts = {}

    def __getitem__(self, key):
        return self.prompts.get(key, self.default_prompts.get(key, f"[Missing Prompt: {key}]"))

    def get_all(self):
        """Returns a merged dictionary of defaults overwritten by custom user prompts."""
        merged = self.default_prompts.copy()
        merged.update(self.prompts)
        return merged

    def save_prompts(self, new_data: dict):
        """Saves updated prompts from the UI to the local config file."""
        self.prompts.update(new_data)
        with open(MICRO_PROMPTS_FILE, "w") as f:
            json.dump(self.prompts, f, indent=4)

MICRO_PROMPTS = PromptManager()