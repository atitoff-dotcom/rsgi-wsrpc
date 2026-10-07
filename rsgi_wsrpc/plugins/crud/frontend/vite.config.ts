import { defineConfig } from 'vite';
import { svelte } from '@sveltejs/vite-plugin-svelte';
import tailwindcss from '@tailwindcss/postcss';
import path from 'node:path';

export default defineConfig({
  base: './',
  plugins: [
    svelte()
  ],
  resolve: {
    alias: {
      '@wsrpc': path.resolve(__dirname, '../../../../client')
    }
  },
  server: {
    fs: {
      allow: [
        '.',
        path.resolve(__dirname, '../../../../client')
      ]
    }
  },
  css: {
    postcss: {
      plugins: [
        tailwindcss()
      ]
    }
  },
  build: {
    outDir: path.resolve(__dirname, '../static'),
    emptyOutDir: true,
    target: 'esnext'
  }
});
