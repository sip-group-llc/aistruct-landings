import type { NextConfig } from 'next';

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // imagem enxuta no Easypanel: só o server + assets, sem node_modules inteiro
  output: 'standalone',
  // 18/08/2026: afiliados -> indicacao (parceiro). Link antigo nao pode quebrar.
  async redirects() {
    return [{ source: '/afiliados', destination: '/indicacao', permanent: true }];
  },
};

export default nextConfig;
