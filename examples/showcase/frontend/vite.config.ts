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
      '@wsrpc': path.resolve(__dirname, '../../../client'),
      '@content': path.resolve(__dirname, '../content')
    }
  },
  server: {
    fs: {
      allow: [
        '.',
        path.resolve(__dirname, '../../../client'),
        path.resolve(__dirname, '../content')
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
    outDir: path.resolve(__dirname, '../public'),
    emptyOutDir: true,
    target: 'esnext'
  }
});
