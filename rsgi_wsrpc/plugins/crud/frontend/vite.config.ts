import { defineConfig } from 'vite';
import { svelte } from '@sveltejs/vite-plugin-svelte';
import tailwindcss from '@tailwindcss/postcss';
import path from 'node:path';

export default defineConfig({
  plugins: [
    svelte()
  ],
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
