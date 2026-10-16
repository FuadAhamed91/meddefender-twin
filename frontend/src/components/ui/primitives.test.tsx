import { fireEvent, render, screen } from "@testing-library/react";
import { beforeAll, describe, expect, it, vi } from "vitest";
import { TRUST } from "../../lib/status";
import { ConfirmDialog, StatusBadge } from "./primitives";

beforeAll(() => {
  // jsdom may not implement modal dialogs; a minimal stand-in is enough for these tests.
  HTMLDialogElement.prototype.showModal ??= function (this: HTMLDialogElement) {
    this.open = true;
  };
  HTMLDialogElement.prototype.close ??= function (this: HTMLDialogElement) {
    this.open = false;
  };
});

describe("StatusBadge", () => {
  it("shows a text label and a description, not just a color", () => {
    render(<StatusBadge status={TRUST.SUSPICIOUS} />);
    const badge = screen.getByText("Suspicious").parentElement!;
    expect(badge).toHaveAttribute("title", TRUST.SUSPICIOUS.description);
    expect(badge.querySelector("svg")).toHaveAttribute("aria-hidden");
  });
});

describe("ConfirmDialog", () => {
  it("requires a justification before a privileged action can be confirmed", () => {
    const onConfirm = vi.fn();
    render(
      <ConfirmDialog open title="Apply containment plan" confirmLabel="Apply plan" onConfirm={onConfirm} onClose={() => undefined}>
        Isolates ICU-GATEWAY-01.
      </ConfirmDialog>,
    );
    const confirm = screen.getByRole("button", { name: "Apply plan", hidden: true });
    expect(confirm).toBeDisabled();

    const field = screen.getByLabelText(/Justification/, { selector: "textarea" });
    fireEvent.change(field, { target: { value: "  Gateway contacted IAM outside policy  " } });
    expect(confirm).toBeEnabled();

    fireEvent.submit(confirm.closest("form")!);
    expect(onConfirm).toHaveBeenCalledWith("Gateway contacted IAM outside policy");
  });
});
