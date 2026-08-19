/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Required by infra/Dockerfile.web, which copies .next/standalone.
  output: 'standalone',
  // The dashboard talks to the API through a same-origin proxy, so no CORS
  // configuration and no API key ever reaches the browser.
  async rewrites() {
    return [
      {
        source: '/api/backend/:path*',
        destination: `${process.env.SIHHAT_API_URL ?? 'http://localhost:8000'}/api/v1/:path*`,
      },
    ];
  },
};

export default nextConfig;
