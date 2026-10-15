import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { LandingPage } from "./LandingPage";

describe("LandingPage", () => {
  it("explains the product without claiming roadmap features are already available", () => {
    render(<MemoryRouter><LandingPage /></MemoryRouter>);
    expect(screen.getByRole("heading", { name: "Make something that matters" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /create your workspace/i })).toHaveAttribute("href", "/register");
    expect(screen.getByText(/research, evidence, requirements, and architecture tools are on the roadmap/i)).toBeInTheDocument();
  });
});
