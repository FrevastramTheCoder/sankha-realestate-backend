import * as sqlite3 from 'sqlite3';
import axios from 'axios';
import { resolve } from 'path';

const DB_PATH = resolve(__dirname, '..', 'dev.db');
const GITHUB_MODELS_URL = 'https://models.github.ai/inference';
const QDRANT_URL = process.env.QDRANT_URL || 'http://localhost:6333';
const TOKEN = process.env.GITHUB_TOKEN || process.env.OPENAI_API_KEY || '';
const EMBEDDING_MODEL = process.env.EMBEDDING_MODEL || 'openai/text-embedding-3-small';
const BATCH_SIZE = 50;
const COLLECTION_NAME = 'properties';
const VECTOR_SIZE = 1536;

interface Property {
  id: string;
  title: string;
  type: string;
  price: number;
  location: string;
  area: string;
  university: string;
  description: string;
  amenities: string;
  rating: number;
  reviewCount: number;
  status: string;
}

const UNIVERSITY_LABELS: Record<string, string> = {
  UDSM: 'University of Dar es Salaam',
  ARU: 'Ardhi University',
  MUHAS: 'Muhimbili University of Health and Allied Sciences',
  DIT: 'Dar es Salaam Institute of Technology',
  CBE: 'College of Business Education',
  IFM: 'Institute of Finance Management',
  DUCE: 'Dar es Salaam University College of Education',
  TIA: 'Tanzania Institute of Accountancy',
  NIT: 'National Institute of Transport',
  OUT: 'Open University of Tanzania',
  SJUIT: 'St Joseph University Tanzania',
  KIU: 'Kampala International University Dar Campus',
  MNMA: 'Mwalimu Nyerere Memorial Academy',
  UoB: 'University of Bagamoyo Dar Campus',
  BOTH: 'All Universities',
};

function log(...args: unknown[]) {
  console.log(`[${new Date().toISOString()}]`, ...args);
}

function propertyToText(property: Property): string {
  return [
    `Property: ${property.title}`,
    `Type: ${property.type}`,
    `Rent: TSh ${Number(property.price).toLocaleString()} per month`,
    `Location: ${property.location}, ${property.area}`,
    `University: ${UNIVERSITY_LABELS[property.university] || property.university}`,
    `Description: ${property.description}`,
    `Amenities: ${property.amenities || 'Not specified'}`,
    `Rating: ${property.rating}/5 from ${property.reviewCount} reviews`,
  ].join('. ');
}

async function loadProperties(): Promise<Property[]> {
  return new Promise((resolvePromise, reject) => {
    const db = new sqlite3.Database(DB_PATH);
    db.all(
      "SELECT * FROM properties WHERE status = 'AVAILABLE'",
      (err, rows) => {
        db.close();
        if (err) reject(err);
        else resolvePromise(rows as Property[]);
      },
    );
  });
}

async function generateEmbeddings(texts: string[]): Promise<number[][]> {
  const response = await axios.post(
    GITHUB_MODELS_URL,
    { model: EMBEDDING_MODEL, input: texts },
    {
      headers: {
        Authorization: `Bearer ${TOKEN}`,
        'Content-Type': 'application/json',
      },
    },
  );

  const data = response.data?.data;
  if (!data || !Array.isArray(data)) throw new Error('Invalid embedding response');

  return data
    .sort((a: { index: number }, b: { index: number }) => a.index - b.index)
    .map((item: { embedding?: number[] }) => item.embedding || []);
}

async function upsertPoints(
  points: Array<{ id: string; vector: number[]; payload: Record<string, unknown> }>,
): Promise<void> {
  const url = `${QDRANT_URL}/collections/${COLLECTION_NAME}/points?wait=true`;
  await axios.put(
    url,
    { points },
    {
      headers: { 'Content-Type': 'application/json' },
    },
  );
}

async function ensureCollection(): Promise<void> {
  try {
    const collectionsResp = await axios.get(`${QDRANT_URL}/collections`);
    const collections = collectionsResp.data?.result?.collections || [];
    const exists = collections.some((c: { name: string }) => c.name === COLLECTION_NAME);

    if (exists) {
      log(`Collection '${COLLECTION_NAME}' already exists`);
      return;
    }

    await axios.put(`${QDRANT_URL}/collections/${COLLECTION_NAME}`, {
      vectors: { size: VECTOR_SIZE, distance: 'Cosine' },
    });
    log(`Collection '${COLLECTION_NAME}' created`);
  } catch (error) {
    log('Failed to ensure collection:', error instanceof Error ? error.message : error);
    throw error;
  }
}

async function getIndexedCount(): Promise<number> {
  try {
    const resp = await axios.get(`${QDRANT_URL}/collections/${COLLECTION_NAME}`);
    return resp.data?.result?.points_count || 0;
  } catch {
    return 0;
  }
}

async function main() {
  log('=== NyumbaSalama Property Indexing ===');
  log(`Qdrant URL: ${QDRANT_URL}`);
  log(`Database: ${DB_PATH}`);

  if (!TOKEN) {
    log('ERROR: No GITHUB_TOKEN or OPENAI_API_KEY set');
    process.exit(1);
  }

  const existingCount = await getIndexedCount();
  log(`Currently indexed points: ${existingCount}`);

  log('Loading properties from database...');
  const properties = await loadProperties();
  log(`Found ${properties.length} available properties`);

  if (properties.length === 0) {
    log('No properties to index. Exiting.');
    return;
  }

  log('Ensuring Qdrant collection exists...');
  await ensureCollection();

  const texts = properties.map((p) => propertyToText(p));
  let indexed = 0;
  let failed = 0;

  for (let i = 0; i < properties.length; i += BATCH_SIZE) {
    const batchProperties = properties.slice(i, i + BATCH_SIZE);
    const batchTexts = texts.slice(i, i + BATCH_SIZE);

    try {
      log(`Embedding batch ${Math.floor(i / BATCH_SIZE) + 1}: ${batchProperties.length} properties (${i + 1}-${Math.min(i + BATCH_SIZE, properties.length)}/${properties.length})...`);
      const vectors = await generateEmbeddings(batchTexts);

      const points = batchProperties.map((p, j) => ({
        id: p.id,
        vector: vectors[j],
        payload: {
          propertyId: p.id,
          title: p.title,
          type: p.type,
          price: p.price,
          location: p.location,
          area: p.area,
          university: p.university,
          universityLabel: UNIVERSITY_LABELS[p.university] || p.university,
          description: p.description,
          amenities: p.amenities,
          rating: p.rating,
          reviewCount: p.reviewCount,
          status: p.status,
        },
      }));

      await upsertPoints(points);
      indexed += points.length;
      log(`Batch uploaded: ${points.length} points (total: ${indexed}/${properties.length})`);
    } catch (error) {
      failed += batchProperties.length;
      log(`Batch FAILED: ${batchProperties.length} properties`, error instanceof Error ? error.message : error);
    }

    if (i + BATCH_SIZE < properties.length) {
      await new Promise((r) => setTimeout(r, 500));
    }
  }

  log(`=== Indexing Complete ===`);
  log(`Successfully indexed: ${indexed}`);
  log(`Failed: ${failed}`);
  log(`Total Qdrant points: ${await getIndexedCount()}`);
}

main().catch((err) => {
  log('FATAL ERROR:', err);
  process.exit(1);
});
