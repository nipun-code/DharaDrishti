import { useCallback, useEffect, useRef, useState } from "react";

import { api, ApiError } from "../api/client";
import type { ReadinessResponse } from "../types/api";

export type ReadinessState =
  | { kind: "loading" }
  | { kind: "error"; error: ApiError }
  | { kind: "success"; data: ReadinessResponse };

export function useReadiness(): { state: ReadinessState; refresh: () => void } {
  const [state, setState] = useState<ReadinessState>({ kind: "loading" });
  const controllerRef = useRef<AbortController | null>(null);

  const refresh = useCallback(() => {
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    setState({ kind: "loading" });

    api
      .getReadiness(controller.signal)
      .then((data) => {
        if (!controller.signal.aborted) setState({ kind: "success", data });
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        const error =
          err instanceof ApiError ? err : new ApiError(0, "unknown", "Unexpected error.", null);
        setState({ kind: "error", error });
      });
  }, []);

  useEffect(() => {
    refresh();
    return () => controllerRef.current?.abort();
  }, [refresh]);

  return { state, refresh };
}
