/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'standalone',
  // Set when deployed under a subpath (e.g. clear-horizon.tech/report). Leave empty or remove for root.
  basePath: process.env.NEXT_PUBLIC_BASE_PATH || '',
};

module.exports = nextConfig;
