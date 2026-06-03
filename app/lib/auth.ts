import { NextRequest, NextResponse } from "next/server";

export function requireAutomationToken(req: NextRequest): NextResponse | null {
  const expected = process.env.APP_INGEST_TOKEN;
  if (!expected) {
    return NextResponse.json(
      { error: "APP_INGEST_TOKEN is required for write endpoints" },
      { status: 503 },
    );
  }

  const header = req.headers.get("authorization") ?? "";
  const token = header.startsWith("Bearer ") ? header.slice("Bearer ".length).trim() : "";
  if (token !== expected) {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }
  return null;
}
