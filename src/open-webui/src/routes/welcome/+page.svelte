<script lang="ts">
	import { onMount } from 'svelte';
	import LandingPage from '$lib/components/LandingPage.svelte';

	onMount(() => {
		// Override app.html scroll locks by injecting inline style properties with important priority
		document.documentElement.style.setProperty('overflow-y', 'auto', 'important');
		document.documentElement.style.setProperty('height', 'auto', 'important');
		document.documentElement.style.setProperty('overscroll-behavior-y', 'auto', 'important');
		
		document.body.style.setProperty('overflow-y', 'auto', 'important');
		document.body.style.setProperty('height', 'auto', 'important');
		document.body.style.setProperty('overscroll-behavior-y', 'auto', 'important');

		return () => {
			document.documentElement.style.removeProperty('overflow-y');
			document.documentElement.style.removeProperty('height');
			document.documentElement.style.removeProperty('overscroll-behavior-y');

			document.body.style.removeProperty('overflow-y');
			document.body.style.removeProperty('height');
			document.body.style.removeProperty('overscroll-behavior-y');
		};
	});
</script>

<LandingPage />
