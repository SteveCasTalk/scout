import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Vinext inspects multipart requests before routing evidence uploads.
  // Allow the 25 MB file limit plus multipart overhead through that layer.
  experimental: { serverActions: { bodySizeLimit: '26mb' } },
};

export default nextConfig;
