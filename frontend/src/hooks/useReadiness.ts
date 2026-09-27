import { useCallback, useEffect, useRef, useState } from "react";

import { api, ApiError } from "../api/client";
import type { ReadinessResponse } from "../types/api";

export type ReadinessState =
  | { kind: "loading" }
  | { kind: "error"; error: ApiError }
  | { kind: "success"; data: ReadinessResponse };

/** Polls /health/ready (optionally every `intervalMs`). */
export function useReadiness(intervalMs?: number): { state: ReadinessState; refresh: () => void } {
  const [state, setState] = useState<ReadinessState>({ kind: "loading" });
  const controllerRef = useRef<AbortController | null>(null);

  const refresh = useCallback(() => {
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    api.health
      .ready(controller.signal)
      .then((data) => {
        if (!controller.signal.aborted) setState({ kind: "success", data });
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        setState({
          kind: "error",
          error:
            err instanceof ApiError
              ? err
              : new ApiError(0, { code: "unknown", message: "Unexpected error.", request_id: null }),
        });
      });
  }, []);

  useEffect(() => {
    refresh();
    const timer = intervalMs ? window.setInterval(refresh, intervalMs) : undefined;
    return () => {
      controllerRef.current?.abort();
      if (timer) window.clearInterval(timer);
    };
  }, [refresh, intervalMs]);

  return { state, refresh };
}
