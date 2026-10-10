#!/usr/bin/env node
import { main } from '../src/main.mjs';
try { process.exitCode = await main(process.argv.slice(2)); }
catch (error) { console.error(`praxis: ${error.message}`); process.exitCode = 1; }
