import assert from 'node:assert/strict';
import test from 'node:test';
import { pontoNaImagem } from '../src/esferoides/revisor/web/validacao_canvas.js';

test('zoom e pan preservam as coordenadas no canvas nativo de 1368 × 1038', () => {
  const w = 1368;
  const h = 1038;
  for (const escala of [0.25, 0.5, 1, 1.25, 2, 8]) {
    const bounds = { left: -145.5, top: 72.25, width: w * escala, height: h * escala };
    for (const [x, y] of [[0, 0], [421, 500], [855.5, 924.25], [1367, 1037]]) {
      const cliX = bounds.left + x * escala;
      const cliY = bounds.top + y * escala;
      assert.deepEqual(pontoNaImagem(cliX, cliY, bounds, w, h), [x, y]);
    }
  }
});
