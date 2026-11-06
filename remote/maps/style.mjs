// The basemap's style for the tile server, from Protomaps' style package (maps.sh build,
// in a Node container, online). Everything it names is on the box: the tiles are the
// tile server's `basemap` source, the fonts and icons its own folders.
//
//   node style.mjs <out.json> <flavor> <lang>
import { writeFileSync } from 'node:fs';
import { layers, namedFlavor } from '@protomaps/basemaps';

const [out, flavor, lang] = process.argv.slice(2);
const style = {
  version: 8,
  name: 'Kobo in a box',
  sources: {
    protomaps: {
      type: 'vector',
      url: 'pmtiles://{basemap}',
      attribution: '© OpenStreetMap contributors · Protomaps',
    },
  },
  layers: layers('protomaps', namedFlavor(flavor), { lang }),
  glyphs: '{fontstack}/{range}.pbf',
  sprite: flavor,
};
writeFileSync(out, JSON.stringify(style, null, 1));
console.log(`${style.layers.length} layers, labels in ${lang}`);
