<script lang="ts">
	import Switch from '$lib/components/common/Switch.svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import { getContext } from 'svelte';

	const i18n: any = getContext('i18n');

	export let onChange: (params: any) => void = () => {};
	export let admin = false;
	export let custom = false;

	$: admin;
	$: custom;

	const defaultParams: Record<string, any> = {
		retrieval_mode: null,
		top_k: null,
		rerank_enabled: null,
		rerank_model: null,
		graph_enabled: null,
		max_hops: null,
		llm_temperature: null,
		max_context_chunks: null,
		llm_max_tokens: null,
		llm_streaming: null,
		agent_enabled: null
	};

	export let params: Record<string, any> = defaultParams;

	const defaults: Record<string, any> = {
		retrieval_mode: 'hybrid',
		top_k: 5,
		rerank_enabled: true,
		rerank_model: 'rerank-2.5',
		graph_enabled: true,
		max_hops: 2,
		llm_temperature: 0.2,
		max_context_chunks: 8,
		llm_max_tokens: 16384,
		llm_streaming: true,
		agent_enabled: false
	};

	const toggleParam = (key: string) => {
		params[key] = (params?.[key] ?? null) === null ? defaults[key] : null;
		params = { ...params };
	};

	$: if (params) {
		onChange(params);
	}
</script>

<div class="space-y-1 text-xs pb-safe-bottom">
	<div class="py-0.5 w-full justify-between">
		<Tooltip
			content={i18n.t('Retrieval mode used by VietLegal RAG: dense, sparse, or hybrid.')}
			placement="top-start"
			className="inline-tooltip"
		>
			<div class="flex w-full justify-between">
				<div class="self-center text-xs">{'retrieval_mode'}</div>
				<button
					class="p-1 px-3 text-xs flex rounded-sm transition shrink-0 outline-hidden"
					type="button"
					on:click={() => toggleParam('retrieval_mode')}
				>
					<span class="ml-2 self-center">
						{(params?.retrieval_mode ?? null) === null ? i18n.t('Default') : i18n.t('Custom')}
					</span>
				</button>
			</div>
		</Tooltip>

		{#if (params?.retrieval_mode ?? null) !== null}
			<div class="flex mt-0.5">
				<select
					class="w-full rounded-lg py-2 px-3 text-sm dark:text-gray-300 dark:bg-gray-850 outline-hidden border border-gray-100/30 dark:border-gray-850/30"
					bind:value={params.retrieval_mode}
				>
					<option value="dense">dense</option>
					<option value="sparse">sparse</option>
					<option value="hybrid">hybrid</option>
				</select>
			</div>
		{/if}
	</div>

	<div class="py-0.5 w-full justify-between">
		<Tooltip
			content={i18n.t('Number of corpus chunks retrieved before answer generation.')}
			placement="top-start"
			className="inline-tooltip"
		>
			<div class="flex w-full justify-between">
				<div class="self-center text-xs">{'top_k'}</div>
				<button
					class="p-1 px-3 text-xs flex rounded-sm transition shrink-0 outline-hidden"
					type="button"
					on:click={() => toggleParam('top_k')}
				>
					<span class="ml-2 self-center">
						{(params?.top_k ?? null) === null ? i18n.t('Default') : i18n.t('Custom')}
					</span>
				</button>
			</div>
		</Tooltip>

		{#if (params?.top_k ?? null) !== null}
			<div class="flex mt-0.5 space-x-2">
				<div class="flex-1">
					<input
						type="range"
						min="1"
						max="50"
						step="1"
						bind:value={params.top_k}
						class="w-full h-2 rounded-lg appearance-none cursor-pointer dark:bg-gray-700"
					/>
				</div>
				<input
					bind:value={params.top_k}
					type="number"
					class="bg-transparent text-center w-14"
					min="1"
					max="50"
					step="1"
				/>
			</div>
		{/if}
	</div>

	<div class="py-0.5 w-full justify-between">
		<Tooltip
			content={i18n.t('Enable or disable reranking for retrieved legal chunks.')}
			placement="top-start"
			className="inline-tooltip"
		>
			<div class="flex w-full justify-between">
				<div class="self-center text-xs">{'rerank_enabled'}</div>
				<button
					class="p-1 px-3 text-xs flex rounded-sm transition shrink-0 outline-hidden"
					type="button"
					on:click={() => toggleParam('rerank_enabled')}
				>
					<span class="ml-2 self-center">
						{(params?.rerank_enabled ?? null) === null ? i18n.t('Default') : i18n.t('Custom')}
					</span>
				</button>
			</div>
		</Tooltip>

		{#if (params?.rerank_enabled ?? null) !== null}
			<div class="flex justify-between items-center mt-0.5">
				<div class="text-xs text-gray-500">
					{params.rerank_enabled ? i18n.t('Enabled') : i18n.t('Disabled')}
				</div>
				<div class="pr-2">
					<Switch bind:state={params.rerank_enabled} />
				</div>
			</div>
		{/if}
	</div>

	<div class="py-0.5 w-full justify-between">
		<Tooltip
			content={i18n.t('Reranker model identifier passed to the retrieval request.')}
			placement="top-start"
			className="inline-tooltip"
		>
			<div class="flex w-full justify-between">
				<div class="self-center text-xs">{'rerank_model'}</div>
				<button
					class="p-1 px-3 text-xs flex rounded-sm transition shrink-0 outline-hidden"
					type="button"
					on:click={() => toggleParam('rerank_model')}
				>
					<span class="ml-2 self-center">
						{(params?.rerank_model ?? null) === null ? i18n.t('Default') : i18n.t('Custom')}
					</span>
				</button>
			</div>
		</Tooltip>

		{#if (params?.rerank_model ?? null) !== null}
			<input
				class="text-sm w-full bg-transparent outline-hidden outline-none mt-0.5"
				type="text"
				placeholder="rerank-2.5"
				bind:value={params.rerank_model}
				autocomplete="off"
			/>
		{/if}
	</div>

	<div class="py-0.5 w-full justify-between">
		<Tooltip
			content={i18n.t('Enable or disable Neo4j graph traversal for this request.')}
			placement="top-start"
			className="inline-tooltip"
		>
			<div class="flex w-full justify-between">
				<div class="self-center text-xs">{'graph_enabled'}</div>
				<button
					class="p-1 px-3 text-xs flex rounded-sm transition shrink-0 outline-hidden"
					type="button"
					on:click={() => toggleParam('graph_enabled')}
				>
					<span class="ml-2 self-center">
						{(params?.graph_enabled ?? null) === null ? i18n.t('Default') : i18n.t('Custom')}
					</span>
				</button>
			</div>
		</Tooltip>

		{#if (params?.graph_enabled ?? null) !== null}
			<div class="flex justify-between items-center mt-0.5">
				<div class="text-xs text-gray-500">
					{params.graph_enabled ? i18n.t('Enabled') : i18n.t('Disabled')}
				</div>
				<div class="pr-2">
					<Switch bind:state={params.graph_enabled} />
				</div>
			</div>
		{/if}
	</div>

	<div class="py-0.5 w-full justify-between">
		<Tooltip
			content={i18n.t(
				'Maximum graph traversal hops. VietLegal RAG currently validates this from 0 to 2.'
			)}
			placement="top-start"
			className="inline-tooltip"
		>
			<div class="flex w-full justify-between">
				<div class="self-center text-xs">{'max_hops'}</div>
				<button
					class="p-1 px-3 text-xs flex rounded-sm transition shrink-0 outline-hidden"
					type="button"
					on:click={() => toggleParam('max_hops')}
				>
					<span class="ml-2 self-center">
						{(params?.max_hops ?? null) === null ? i18n.t('Default') : i18n.t('Custom')}
					</span>
				</button>
			</div>
		</Tooltip>

		{#if (params?.max_hops ?? null) !== null}
			<div class="flex mt-0.5 space-x-2">
				<div class="flex-1">
					<input
						type="range"
						min="0"
						max="2"
						step="1"
						bind:value={params.max_hops}
						class="w-full h-2 rounded-lg appearance-none cursor-pointer dark:bg-gray-700"
					/>
				</div>
				<input
					bind:value={params.max_hops}
					type="number"
					class="bg-transparent text-center w-14"
					min="0"
					max="2"
					step="1"
				/>
			</div>
		{/if}
	</div>

	<div class="py-0.5 w-full justify-between">
		<Tooltip
			content={i18n.t('LLM generation temperature used by VietLegal RAG.')}
			placement="top-start"
			className="inline-tooltip"
		>
			<div class="flex w-full justify-between">
				<div class="self-center text-xs">{'llm_temperature'}</div>
				<button
					class="p-1 px-3 text-xs flex rounded-sm transition shrink-0 outline-hidden"
					type="button"
					on:click={() => toggleParam('llm_temperature')}
				>
					<span class="ml-2 self-center">
						{(params?.llm_temperature ?? null) === null ? i18n.t('Default') : i18n.t('Custom')}
					</span>
				</button>
			</div>
		</Tooltip>

		{#if (params?.llm_temperature ?? null) !== null}
			<div class="flex mt-0.5 space-x-2">
				<div class="flex-1">
					<input
						type="range"
						min="0"
						max="1"
						step="0.05"
						bind:value={params.llm_temperature}
						class="w-full h-2 rounded-lg appearance-none cursor-pointer dark:bg-gray-700"
					/>
				</div>
				<input
					bind:value={params.llm_temperature}
					type="number"
					class="bg-transparent text-center w-14"
					min="0"
					max="1"
					step="any"
				/>
			</div>
		{/if}
	</div>

	<div class="py-0.5 w-full justify-between">
		<Tooltip
			content={i18n.t('Maximum context chunks allowed in the answer prompt.')}
			placement="top-start"
			className="inline-tooltip"
		>
			<div class="flex w-full justify-between">
				<div class="self-center text-xs">{'max_context_chunks'}</div>
				<button
					class="p-1 px-3 text-xs flex rounded-sm transition shrink-0 outline-hidden"
					type="button"
					on:click={() => toggleParam('max_context_chunks')}
				>
					<span class="ml-2 self-center">
						{(params?.max_context_chunks ?? null) === null ? i18n.t('Default') : i18n.t('Custom')}
					</span>
				</button>
			</div>
		</Tooltip>

		{#if (params?.max_context_chunks ?? null) !== null}
			<div class="flex mt-0.5 space-x-2">
				<div class="flex-1">
					<input
						type="range"
						min="1"
						max="32"
						step="1"
						bind:value={params.max_context_chunks}
						class="w-full h-2 rounded-lg appearance-none cursor-pointer dark:bg-gray-700"
					/>
				</div>
				<input
					bind:value={params.max_context_chunks}
					type="number"
					class="bg-transparent text-center w-14"
					min="1"
					max="32"
					step="1"
				/>
			</div>
		{/if}
	</div>

	<div class="py-0.5 w-full justify-between">
		<Tooltip
			content={i18n.t('Maximum output tokens for LLM answer generation.')}
			placement="top-start"
			className="inline-tooltip"
		>
			<div class="flex w-full justify-between">
				<div class="self-center text-xs">{'llm_max_tokens'}</div>
				<button
					class="p-1 px-3 text-xs flex rounded-sm transition shrink-0 outline-hidden"
					type="button"
					on:click={() => toggleParam('llm_max_tokens')}
				>
					<span class="ml-2 self-center">
						{(params?.llm_max_tokens ?? null) === null ? i18n.t('Default') : i18n.t('Custom')}
					</span>
				</button>
			</div>
		</Tooltip>

		{#if (params?.llm_max_tokens ?? null) !== null}
			<div class="flex mt-0.5 space-x-2">
				<div class="flex-1">
					<input
						type="range"
						min="1"
						max="131072"
						step="1"
						bind:value={params.llm_max_tokens}
						class="w-full h-2 rounded-lg appearance-none cursor-pointer dark:bg-gray-700"
					/>
				</div>
				<input
					bind:value={params.llm_max_tokens}
					type="number"
					class="bg-transparent text-center w-20"
					min="1"
					step="1"
				/>
			</div>
		{/if}
	</div>

	<div class="py-0.5 w-full justify-between">
		<Tooltip
			content={i18n.t('Stream response tokens from VietLegal RAG when available.')}
			placement="top-start"
			className="inline-tooltip"
		>
			<div class="flex w-full justify-between">
				<div class="self-center text-xs">{'llm_streaming'}</div>
				<button
					class="p-1 px-3 text-xs flex rounded-sm transition shrink-0 outline-hidden"
					type="button"
					on:click={() => toggleParam('llm_streaming')}
				>
					<span class="ml-2 self-center">
						{(params?.llm_streaming ?? null) === null ? i18n.t('Default') : i18n.t('Custom')}
					</span>
				</button>
			</div>
		</Tooltip>

		{#if (params?.llm_streaming ?? null) !== null}
			<div class="flex justify-between items-center mt-0.5">
				<div class="text-xs text-gray-500">
					{params.llm_streaming ? i18n.t('Enabled') : i18n.t('Disabled')}
				</div>
				<div class="pr-2">
					<Switch bind:state={params.llm_streaming} />
				</div>
			</div>
		{/if}
	</div>

	<div class="py-0.5 w-full justify-between">
		<Tooltip
			content={i18n.t(
				'Use the LangGraph agent path if the service is configured. This can disable agent mode per chat, but cannot enable it if the backend service was not initialized.'
			)}
			placement="top-start"
			className="inline-tooltip"
		>
			<div class="flex w-full justify-between">
				<div class="self-center text-xs">{'agent_enabled'}</div>
				<button
					class="p-1 px-3 text-xs flex rounded-sm transition shrink-0 outline-hidden"
					type="button"
					on:click={() => toggleParam('agent_enabled')}
				>
					<span class="ml-2 self-center">
						{(params?.agent_enabled ?? null) === null ? i18n.t('Default') : i18n.t('Custom')}
					</span>
				</button>
			</div>
		</Tooltip>

		{#if (params?.agent_enabled ?? null) !== null}
			<div class="flex justify-between items-center mt-0.5">
				<div class="text-xs text-gray-500">
					{params.agent_enabled ? i18n.t('Enabled') : i18n.t('Disabled')}
				</div>
				<div class="pr-2">
					<Switch bind:state={params.agent_enabled} />
				</div>
			</div>
		{/if}
	</div>
</div>
