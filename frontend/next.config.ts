import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  /* config options here */
  allowedDevOrigins: ['192.168.0.108', 'localhost', '127.0.0.1'],
  devIndicators: false,
};

export default nextConfig;
