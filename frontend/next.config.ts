import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  allowedDevOrigins: ['192.168.0.108', 'localhost', '127.0.0.1', '*.trycloudflare.com'],
  devIndicators: false,
};

export default nextConfig;
