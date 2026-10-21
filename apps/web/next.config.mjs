const api = process.env.TRACKER_API_URL ?? "http://127.0.0.1:8040";

/** Everything goes through this one address: the browser and the agent call /api/*, which is the API. */
export default {
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${api}/:path*` }];
  },
  experimental: {
    // Exports of a whole team can take a while; the proxy's default 30 s would cut them off.
    proxyTimeout: 600_000,
  },
};
