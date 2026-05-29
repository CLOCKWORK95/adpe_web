const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const SITE_URL = (process.env.ADPE_SITE_URL || 'https://adpe.it').replace(/\/+$/, '');

function readText(fileName) {
  return fs.readFileSync(path.join(ROOT, fileName), 'utf8');
}

function readJson(fileName) {
  return JSON.parse(readText(fileName));
}

function ensureDir(dir) {
  fs.mkdirSync(dir, { recursive: true });
}

function slugifySegment(value) {
  return String(value || '')
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
}

function buildProjectSlug(categoryPath) {
  return String(categoryPath || '').split('.').map(slugifySegment).filter(Boolean).join('/');
}

function flattenProjects(node, currentPath = '', result = []) {
  for (const [key, child] of Object.entries(node)) {
    const nextPath = currentPath ? `${currentPath}.${key}` : key;
    if (child && typeof child === 'object' && !Array.isArray(child)) {
      if (Array.isArray(child.images)) {
        result.push({ ...child, categoryPath: nextPath, slug: buildProjectSlug(nextPath) });
      } else {
        flattenProjects(child, nextPath, result);
      }
    }
  }
  return result;
}

function stripHtml(value) {
  return String(value || '')
    .replace(/<[^>]*>/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

function truncate(value, maxLength) {
  const text = stripHtml(value);
  if (text.length <= maxLength) return text;
  return `${text.slice(0, maxLength - 1).trim()}...`;
}

function imageVariant(image, preferred = 'src') {
  if (!image) return '';
  const fallbacks = {
    large: ['large', 'medium', 'src', 'thumb'],
    src: ['src', 'large', 'medium', 'thumb']
  };
  for (const key of (fallbacks[preferred] || fallbacks.src)) {
    if (image[key]) return image[key];
  }
  return '';
}

function escapeAttr(value) {
  return String(value || '')
    .replace(/&/g, '&amp;')
    .replace(/"/g, '&quot;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

function escapeScriptJson(value) {
  return JSON.stringify(value).replace(/</g, '\\u003c');
}

function replaceOrInsertMeta(html, selector, replacement) {
  const regexes = {
    description: /<meta\s+name=["']description["'][^>]*>/i,
    ogTitle: /<meta\s+property=["']og:title["'][^>]*>/i,
    ogDescription: /<meta\s+property=["']og:description["'][^>]*>/i,
    ogImage: /<meta\s+property=["']og:image["'][^>]*>/i,
    ogType: /<meta\s+property=["']og:type["'][^>]*>/i
  };

  const regex = regexes[selector];
  if (regex && regex.test(html)) return html.replace(regex, replacement);
  return html.replace('</head>', `  ${replacement}\n</head>`);
}

function buildProjectPage(indexHtml, project) {
  const title = `${stripHtml(project.title)} | ADPE`;
  const description = truncate(project.description || project.luogo_data || 'Progetto ADPE Studio di Architettura.', 155);
  const image = project.images && project.images[0] ? imageVariant(project.images[0], 'large') : '';
  const canonical = `${SITE_URL}/progetti/${project.slug}/`;
  const jsonLd = {
    '@context': 'https://schema.org',
    '@type': 'CreativeWork',
    name: stripHtml(project.title),
    description,
    image,
    url: canonical,
    creator: {
      '@type': 'Organization',
      name: 'ADPE Studio di Architettura'
    }
  };

  let html = indexHtml;
  html = html.replace(/<title[^>]*>[\s\S]*?<\/title>/i, `<title>${escapeAttr(title)}</title>`);
  html = replaceOrInsertMeta(html, 'description', `<meta name="description" content="${escapeAttr(description)}">`);
  html = replaceOrInsertMeta(html, 'ogTitle', `<meta property="og:title" content="${escapeAttr(title)}">`);
  html = replaceOrInsertMeta(html, 'ogDescription', `<meta property="og:description" content="${escapeAttr(description)}">`);
  if (image) html = replaceOrInsertMeta(html, 'ogImage', `<meta property="og:image" content="${escapeAttr(image)}">`);
  html = replaceOrInsertMeta(html, 'ogType', '<meta property="og:type" content="article">');

  html = html.replace('<head>', '<head>\n  <base href="/">');
  html = html.replace(
    '</head>',
    `  <link rel="canonical" href="${escapeAttr(canonical)}">\n  <meta property="og:url" content="${escapeAttr(canonical)}">\n  <script type="application/ld+json">${escapeScriptJson(jsonLd)}</script>\n</head>`
  );

  html = html.replace(
    /(\s*<script>\s*\/\/ =========================================================================\s*\/\/ CDN \/ IMAGE OPTIMIZATION)/,
    `\n  <script>window.__ADPE_INITIAL_PROJECT_SLUG__ = ${escapeScriptJson(project.slug)};</script>\n$1`
  );

  return html;
}

function writeSitemap(projects) {
  const staticUrls = [
    `${SITE_URL}/`,
    `${SITE_URL}/?view=projects`,
    `${SITE_URL}/?view=about`,
    `${SITE_URL}/?view=contact`
  ];
  const projectUrls = projects.map(project => `${SITE_URL}/progetti/${project.slug}/`);
  const urls = [...staticUrls, ...projectUrls];
  const body = urls.map(url => `  <url><loc>${escapeAttr(url)}</loc></url>`).join('\n');
  const sitemap = `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n${body}\n</urlset>\n`;
  fs.writeFileSync(path.join(ROOT, 'sitemap.xml'), sitemap, 'utf8');
}

function writeRobots() {
  const robots = `User-agent: *\nAllow: /\nSitemap: ${SITE_URL}/sitemap.xml\n`;
  fs.writeFileSync(path.join(ROOT, 'robots.txt'), robots, 'utf8');
}

function main() {
  const indexHtml = readText('index.html');
  const projects = flattenProjects(readJson('projects.json'));
  const outputRoot = path.join(ROOT, 'progetti');

  ensureDir(outputRoot);

  for (const project of projects) {
    const outputDir = path.join(outputRoot, ...project.slug.split('/'));
    ensureDir(outputDir);
    fs.writeFileSync(path.join(outputDir, 'index.html'), buildProjectPage(indexHtml, project), 'utf8');
  }

  writeSitemap(projects);
  writeRobots();
  console.log(`Generated ${projects.length} project pages, sitemap.xml and robots.txt`);
}

main();
