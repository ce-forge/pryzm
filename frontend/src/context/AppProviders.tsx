"use client";

import React from "react";
import { WorkspaceProvider } from "@/context/WorkspaceContext";
import { SessionProvider } from "@/context/SessionContext";
import { InferenceProvider } from "@/context/InferenceContext";
import { UploaderProvider } from "@/context/UploaderContext";
import { TestSuiteProvider } from "@/context/TestSuiteContext";

/**
 * Composition order matters: lower providers consume higher ones via their
 * useXxxContext() hooks (e.g. InferenceProvider reads SessionContext).
 */
export function AppProviders({ children }: { children: React.ReactNode }) {
  return (
    <WorkspaceProvider>
      <SessionProvider>
        <InferenceProvider>
          <UploaderProvider>
            <TestSuiteProvider>{children}</TestSuiteProvider>
          </UploaderProvider>
        </InferenceProvider>
      </SessionProvider>
    </WorkspaceProvider>
  );
}
