import type { NextConfig } from "next";
import { sourceIdentity } from "./build/source-identity.mjs";

const nextConfig: NextConfig = {
  env: { SCOUT_DASHBOARD_SOURCE_SHA256: sourceIdentity(process.cwd()) },
  // Vinext inspects multipart requests before routing evidence uploads.
  // Allow the 25 MB file limit plus multipart overhead through that layer.
  experimental: { serverActions: { bodySizeLimit: '26mb' } },
};

export default nextConfig;
