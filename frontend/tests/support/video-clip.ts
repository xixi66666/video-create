import type {Page} from '@playwright/test'
import fs from 'node:fs'

export async function clip(_page:Page,color:string){return fs.readFileSync(new URL(color==='#467467'?'../fixtures/green.webm':'../fixtures/blue.webm',import.meta.url))}
