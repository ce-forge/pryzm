import os
import json
import shutil
import time

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
            # The previous behaviour set self.prompts = {} and continued, which
            # silently let the next save_prompts() overwrite the corrupt file
            # with an empty dict — wiping any per-user overrides we couldn't
            # read. Move the broken file aside instead so the user can recover
            # it manually, then start fresh.
            backup = f"{MICRO_PROMPTS_FILE}.corrupted-{int(time.time())}"
            try:
                os.rename(MICRO_PROMPTS_FILE, backup)
                print(
                    f"Warning: micro_prompts.json was unreadable ({e}). "
                    f"Moved to {backup}; starting with defaults."
                )
            except OSError as rename_err:
                print(
                    f"Warning: micro_prompts.json was unreadable ({e}) and could "
                    f"not be backed up ({rename_err}). Continuing with defaults; "
                    f"any save will overwrite the broken file."
                )
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
        self._flush()

    def delete_prompt(self, key: str) -> bool:
        """Remove a per-user prompt override. Returns True if a key was removed,
        False if it wasn't present. The default-file entry (if any) is left
        intact; the next __getitem__ for `key` will fall back to the default.
        """
        if key not in self.prompts:
            return False
        self.prompts.pop(key)
        self._flush()
        return True

    def _flush(self) -> None:
        with open(MICRO_PROMPTS_FILE, "w") as f:
            json.dump(self.prompts, f, indent=4)

MICRO_PROMPTS = PromptManager()