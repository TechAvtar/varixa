import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  experimental: {
    // Image uploads travel through a server action; match the API's VERIXA_MAX_UPLOAD_BYTES.
    serverActions: { bodySizeLimit: "26mb" },
  },
};

export default nextConfig;
