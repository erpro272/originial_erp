import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { readMode, resolve, setLocalMode } from "@/lib/theme";
import { json, mockApi, route } from "@/test/utils";
import { ThemeToggle } from "./ThemeToggle";

function fakeSystem(dark: boolean) {
  vi.stubGlobal("matchMedia", (q: string) => ({
    matches: dark && q.includes("dark"),
    media: q,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
  }));
}

describe("light / dark mode", () => {
  beforeEach(() => {
    localStorage.clear();
    delete document.documentElement.dataset.theme;
  });
  afterEach(() => vi.unstubAllGlobals());

  it("follows the device until the user chooses, then remembers the choice", () => {
    fakeSystem(true);
    expect(readMode()).toBe("system");
    expect(resolve("system")).toBe("dark");
    fakeSystem(false);
    expect(resolve("system")).toBe("light");
    act(() => setLocalMode("dark"));
    expect(readMode()).toBe("dark");
    expect(document.documentElement.dataset.theme).toBe("dark");
    act(() => setLocalMode("system"));
    expect(localStorage.getItem("erp.theme")).toBeNull();
    expect(document.documentElement.dataset.theme).toBe("light");
  });

  it("switches from the top-bar menu and saves the choice on the account", async () => {
    fakeSystem(false);
    const { calls } = mockApi(
      route("PUT", "/api/me/preferences/ui.theme", () =>
        json({ key: "ui.theme", value: { mode: "dark" } }),
      ),
    );
    render(<ThemeToggle />);
    const btn = screen.getByRole("button", { name: "Theme: system (light)" });
    await userEvent.click(btn);
    await userEvent.click(await screen.findByRole("menuitem", { name: /Dark/ }));
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(screen.getByRole("button", { name: "Theme: dark" })).toBeInTheDocument();
    await waitFor(() => expect(calls.some((c) => c.method === "PUT")).toBe(true));
    const put = calls.find((c) => c.method === "PUT")!;
    expect(await put.json()).toEqual({ value: { mode: "dark" } });
  });
});
