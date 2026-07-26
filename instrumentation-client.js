import posthog from 'posthog-js'

const key = process.env.NEXT_PUBLIC_POSTHOG_KEY
const host = process.env.NEXT_PUBLIC_POSTHOG_HOST

if (!key) {
  if (process.env.NODE_ENV !== 'production') {
    console.error(
      'NEXT_PUBLIC_POSTHOG_KEY variable required by PostHog is missing or un-configured, ' +
      'this causes events to be silently missed. ' +
      'This error stops appearing once NEXT_PUBLIC_POSTHOG_KEY is configured'
    )
  }
} else {
  posthog.init(key, {
    api_host: '/ph',
    ui_host: host || 'https://us.posthog.com',
    defaults: '2026-01-30',
    capture_exceptions: true,
    person_profiles: 'identified_only',
    capture_pageview: true,
    capture_pageleave: true,
    debug: process.env.NODE_ENV === 'development',
  })
}
