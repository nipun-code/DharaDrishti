import { useCallback, useEffect, useRef, useState } from "react";

import { api, ApiError, describeError } from "../api/client";
import type { Citation, PipelineStage, QueryResponse, RetrievalMode } from "../types/api";

export interface ChatMessage {
  id: string;
  question: string;
  acts: string[];
  mode: RetrievalMode;
  status: "streaming" | "done" | "error";
  stage: PipelineStage | null;
  completedStages: PipelineStage[];
  draft: string; // streamed tokens (raw draft)
  citations: Citation[];
  response: QueryResponse | null; // verified final answer (replaces the draft)
  error: string | null;
  feedback: 1 | -1 | null;
}

const RECENT_KEY = "dd.recent";
const MAX_RECENT = 8;

function loadRecent(): string[] {
  try {
    const value: unknown = JSON.parse(localStorage.getItem(RECENT_KEY) ?? "[]");
    return Array.isArray(value) ? value.filter((v): v is string => typeof v === "string") : [];
  } catch {
    return [];
  }
}

function saveRecent(list: string[]): void {
  try {
    localStorage.setItem(RECENT_KEY, JSON.stringify(list));
  } catch {
    /* ignore */
  }
}

let counter = 0;
const newId = () => `m${Date.now().toString(36)}${(counter++).toString(36)}`;

export function useChat() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [recent, setRecent] = useState<string[]>(loadRecent);
  const controller = useRef<AbortController | null>(null);

  useEffect(() => () => controller.current?.abort(), []);

  const update = useCallback((id: string, patch: (m: ChatMessage) => Partial<ChatMessage>) => {
    setMessages((list) => list.map((m) => (m.id === id ? { ...m, ...patch(m) } : m)));
  }, []);

  const remember = useCallback((question: string) => {
    setRecent((list) => {
      const next = [question, ...list.filter((q) => q !== question)].slice(0, MAX_RECENT);
      saveRecent(next);
      return next;
    });
  }, []);

  const clearRecent = useCallback(() => {
    saveRecent([]);
    setRecent([]);
  }, []);

  const ask = useCallback(
    async (question: string, acts: string[], mode: RetrievalMode) => {
      controller.current?.abort();
      const abort = new AbortController();
      controller.current = abort;
      const id = newId();
      setMessages((list) => [
        ...list,
        {
          id,
          question,
          acts,
          mode,
          status: "streaming",
          stage: null,
          completedStages: [],
          draft: "",
          citations: [],
          response: null,
          error: null,
          feedback: null,
        },
      ]);
      remember(question);

      try {
        await api.query.stream(
          { query: question, acts: acts.length ? acts : null, mode },
          (event) => {
            switch (event.type) {
              case "status":
                update(id, (m) => ({
                  stage: event.stage,
                  completedStages: m.stage && m.stage !== event.stage ? [...m.completedStages, m.stage] : m.completedStages,
                }));
                break;
              case "token":
                update(id, (m) => ({ draft: m.draft + event.text }));
                break;
              case "citations":
                update(id, () => ({ citations: event.citations }));
                break;
              case "done":
                update(id, (m) => ({
                  status: "done",
                  response: event.response,
                  citations: event.response.citations,
                  completedStages: m.stage ? [...m.completedStages, m.stage] : m.completedStages,
                  stage: null,
                }));
                break;
              case "error":
                update(id, () => ({ status: "error", error: event.error.message, stage: null }));
                break;
            }
          },
          abort.signal,
        );
        // A stream that ends without "done" or "error" (e.g. connection dropped).
        update(id, (m) =>
          m.status === "streaming"
            ? { status: "error", stage: null, error: "The connection closed before the answer finished." }
            : {},
        );
      } catch (err) {
        if (err instanceof DOMException && err.name === "AbortError") {
          update(id, (m) => ({ status: "error", stage: null, error: m.draft ? "Stopped." : "Cancelled." }));
          return;
        }
        const message =
          err instanceof ApiError && err.status === 429 ? `${err.message}` : describeError(err);
        update(id, () => ({ status: "error", stage: null, error: message }));
      } finally {
        if (controller.current === abort) controller.current = null;
      }
    },
    [remember, update],
  );

  const stop = useCallback(() => controller.current?.abort(), []);

  const setFeedback = useCallback(
    (id: string, rating: 1 | -1) => update(id, () => ({ feedback: rating })),
    [update],
  );

  const reset = useCallback(() => {
    controller.current?.abort();
    setMessages([]);
  }, []);

  const busy = messages.some((m) => m.status === "streaming");
  return { messages, recent, busy, ask, stop, reset, clearRecent, setFeedback };
}
