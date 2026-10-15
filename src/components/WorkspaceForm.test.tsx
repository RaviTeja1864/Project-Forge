import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { WorkspaceForm } from "./WorkspaceForm";

describe("WorkspaceForm", () => {
  it("prevents empty names and duplicate submission while saving", async () => {
    const onSubmit = vi.fn(() => new Promise<void>(() => {}));
    render(<WorkspaceForm submitLabel="Create workspace" onSubmit={onSubmit} />);
    fireEvent.click(screen.getByRole("button", { name: "Create workspace" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Give your workspace a name");
    expect(onSubmit).not.toHaveBeenCalled();

    fireEvent.change(screen.getByLabelText("Workspace name"), { target: { value: "A useful project" } });
    fireEvent.click(screen.getByRole("button", { name: "Create workspace" }));
    expect(await screen.findByRole("button", { name: "Saving..." })).toBeDisabled();
    expect(onSubmit).toHaveBeenCalledTimes(1);
  });
});
