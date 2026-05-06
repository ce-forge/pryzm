# Pryzm Frontend

The frontend is a Next.js application styled with Tailwind CSS. It is designed to mirror modern AI chat interfaces while providing advanced file management and markdown rendering capabilities.

## Setup Instructions

1. Install Node.js dependencies:
   ```bash
   npm install
   ```
2. Start the development server:
   ```bash
   npm run dev
   ```
The interface will be accessible at `http://localhost:3000`.

## Core Components

* **`useChatLogic.ts`**: A robust custom hook that extracts all state management from the UI. It manages the fetch streams, abort controllers for stopping generation, upload queues, and parses hidden metadata tags (like `[Attached_File: ...]`) out of user prompts.
* **`chatui.tsx`**: The main chat window. It features:
  * Drag-and-drop file upload overlay.
  * `react-markdown` integration for rendering AI responses.
  * Custom `react-syntax-highlighter` integration for hydration-safe, VS-Code styled code blocks with working "Copy" buttons.
  * Custom blockquote styling for RAG context citations.
* **`sidebar.tsx`**: The navigation menu. Features database-backed folders, drag-and-drop log organization, session pinning, and workspace switching.

## State Management Notes
Session updates (like dynamic title generation) use a combination of local component state and global `window.dispatchEvent` calls to ensure the Sidebar and ChatUI stay synchronized without needing a heavy state management library like Redux.
