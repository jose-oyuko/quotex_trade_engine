// GENERATED from docs/openapi.json by scripts/api-types.mjs. Do not edit: run `npm run api:generate`.

export interface paths {
    "/api/v1/account": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Account */
        get: operations["get_account_api_v1_account_get"];
        /**
         * Set Account
         * @description Switch between demo and real. Refused while a chain or trade is running. REAL also needs the
         *     owner's permission (`PUT /account/real-trading`, decision D-15) and the owner's password again:
         *     this is the one request that makes trades use real money.
         */
        put: operations["set_account_api_v1_account_put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/account/real-trading": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        /**
         * Set Real Trading
         * @description Allow, or stop allowing, the switch to the REAL account. Needs the owner's password. It is
         *     written to the risk log. Taking it back is refused while REAL is the account in use.
         */
        put: operations["set_real_trading_api_v1_account_real_trading_put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/auth/login": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Login */
        post: operations["login_api_v1_auth_login_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/auth/logout": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Logout
         * @description End this browser's session. Fine to call when not logged in.
         */
        post: operations["logout_api_v1_auth_logout_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/auth/password": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Change Password
         * @description Change the password. Every other logged-in browser is logged out.
         */
        post: operations["change_password_api_v1_auth_password_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/auth/setup": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Setup
         * @description Create the owner account (once). The setup code is printed in the application's log.
         */
        post: operations["setup_api_v1_auth_setup_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/auth/state": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get State
         * @description Is an owner account still to be created, and is this browser logged in?
         */
        get: operations["get_state_api_v1_auth_state_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/chains": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Chains
         * @description Newest first. The database trails the engine by a moment; the WebSocket snapshot is the
         *     live picture of what is running right now.
         */
        get: operations["list_chains_api_v1_chains_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/chains/{chain_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Chain */
        get: operations["get_chain_api_v1_chains__chain_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/chains/{chain_id}/end": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * End Chain
         * @description End the chain at once, so the group is free for new signals (the dashboard's "skip to
         *     base"). An open trade still settles and is recorded, but nothing follows it.
         */
        post: operations["end_chain_api_v1_chains__chain_id__end_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/chains/{chain_id}/stop-after-current": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Stop After Current
         * @description Let the open trade settle, then end the chain without a further step. Repeating it is
         *     harmless.
         */
        post: operations["stop_after_current_api_v1_chains__chain_id__stop_after_current_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/engine": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Engine State
         * @description Whether the engine is running, why it is not, and which logins it has.
         */
        get: operations["get_engine_state_api_v1_engine_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/engine/restart": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Restart Engine
         * @description Stop and start again, for example after changing a stored login.
         */
        post: operations["restart_engine_api_v1_engine_restart_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/engine/start": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Start Engine
         * @description Start the engine on the DEMO account: it connects to Quotex and Telegram and begins taking
         *     signals. Does nothing if it is running. 409 `engine_start_failed` says why it could not.
         */
        post: operations["start_engine_api_v1_engine_start_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/engine/stop": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Stop Engine
         * @description Stop the engine. Trades that are open stay open on Quotex and run to their expiry; here they
         *     are marked `unknown` straight away (the application can no longer follow them).
         */
        post: operations["stop_engine_api_v1_engine_stop_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/groups": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Groups */
        get: operations["list_groups_api_v1_groups_get"];
        put?: never;
        /** Create Group */
        post: operations["create_group_api_v1_groups_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/groups/{group_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Group */
        get: operations["get_group_api_v1_groups__group_id__get"];
        /**
         * Update Group
         * @description Chains already running keep the settings they started with.
         */
        put: operations["update_group_api_v1_groups__group_id__put"];
        post?: never;
        /**
         * Delete Group
         * @description Only a group with no history can be deleted; otherwise disable it.
         */
        delete: operations["delete_group_api_v1_groups__group_id__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/groups/{group_id}/pause": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Pause Group
         * @description New signals of the group are ignored (and say so); its running chains finish.
         */
        post: operations["pause_group_api_v1_groups__group_id__pause_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/groups/{group_id}/resume": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Resume Group */
        post: operations["resume_group_api_v1_groups__group_id__resume_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/groups/{group_id}/risk": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Group Risk */
        get: operations["get_group_risk_api_v1_groups__group_id__risk_get"];
        /**
         * Set Group Risk
         * @description Works with or without the engine running, so limits can be set before it is enabled.
         */
        put: operations["set_group_risk_api_v1_groups__group_id__risk_put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/health": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Health
         * @description Liveness check. Contains no secrets.
         */
        get: operations["health_api_v1_health_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/kill-switch": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Engage Kill Switch
         * @description No order goes out from now on, follow-ups included. Repeating it is harmless.
         */
        post: operations["engage_kill_switch_api_v1_kill_switch_post"];
        /** Release Kill Switch */
        delete: operations["release_kill_switch_api_v1_kill_switch_delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/quotex/login": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Login Status
         * @description Where the Quotex login is: logged out, talking to Quotex, waiting for the PIN, or logged in.
         *     Safe after a page reload.
         */
        get: operations["login_status_api_v1_quotex_login_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/quotex/login/cancel": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Login Cancel
         * @description Drop a login that is in progress.
         */
        post: operations["login_cancel_api_v1_quotex_login_cancel_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/quotex/login/pin": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Login Pin
         * @description The PIN Quotex e-mailed. The login carries on and the answer says how it ended.
         */
        post: operations["login_pin_api_v1_quotex_login_pin_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/quotex/login/start": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Login Start
         * @description Log in with the stored email and password. If Quotex e-mails a PIN, the answer says
         *     `pin_needed`. Needs the engine stopped. A refused login is not an error here: it comes back as
         *     `logged_out` with the reason in `message`.
         */
        post: operations["login_start_api_v1_quotex_login_start_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/quotex/logout": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Logout
         * @description Forget the stored Quotex login (the engine then logs in with the password). Needs the
         *     engine stopped.
         */
        post: operations["logout_api_v1_quotex_logout_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/reports/breakdown": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Breakdown
         * @description The same figures split by group, asset, strategy, hour of day or weekday.
         */
        get: operations["get_breakdown_api_v1_reports_breakdown_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/reports/depth": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Depth
         * @description How far chains go: how often each step is reached, and what it costs.
         */
        get: operations["get_depth_api_v1_reports_depth_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/reports/equity": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Equity
         * @description The result of each day with trades and the running total, for the profit curve.
         */
        get: operations["get_equity_api_v1_reports_equity_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/reports/export/breakdown.csv": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Export Breakdown Csv
         * @description A breakdown as a CSV file.
         */
        get: operations["export_breakdown_csv_api_v1_reports_export_breakdown_csv_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/reports/export/trades.csv": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Export Trades Csv
         * @description Every trade in the range, whatever its status (the range here is when it was created), as a
         *     UTF-8 CSV with a byte-order mark. Streamed, so a long history does not sit in memory.
         */
        get: operations["export_trades_csv_api_v1_reports_export_trades_csv_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/reports/summary": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Summary
         * @description Profit, win rate, drawdown, streaks and how the win rate compares with break-even.
         */
        get: operations["get_summary_api_v1_reports_summary_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/risk": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Risk */
        get: operations["get_risk_api_v1_risk_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/risk/events": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Risk Events
         * @description Every order a limit blocked and every other safety event, newest first.
         */
        get: operations["list_risk_events_api_v1_risk_events_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/risk/limits": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        /**
         * Set Risk Limits
         * @description Set the global limits. Works with or without the engine running, so they can be set before
         *     it is ever enabled. Today's result is kept: this is no way to reset a stop-loss.
         */
        put: operations["set_risk_limits_api_v1_risk_limits_put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/secrets": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Secrets
         * @description Which secrets are stored, and whether SECRET_KEY can read them. Never a value.
         */
        get: operations["get_secrets_api_v1_secrets_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/secrets/{name}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        /**
         * Put Secret
         * @description Store a secret, encrypted, replacing the earlier one. Needs SECRET_KEY in `backend/.env`.
         */
        put: operations["put_secret_api_v1_secrets__name__put"];
        post?: never;
        /**
         * Delete Secret
         * @description Remove a stored secret. Fine if it was not set.
         */
        delete: operations["delete_secret_api_v1_secrets__name__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/settings": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Settings
         * @description The settings that can be changed here, with where each value comes from.
         */
        get: operations["get_settings_api_v1_settings_get"];
        /**
         * Put Settings
         * @description Save some settings (all or none: a bad value changes nothing). `null` clears a stored one.
         */
        put: operations["put_settings_api_v1_settings_put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/settings/env-logins": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Env Logins
         * @description Which logins are still written in `backend/.env`, and which of those are already stored.
         *     Never a value.
         */
        get: operations["get_env_logins_api_v1_settings_env_logins_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/settings/env-logins/import": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Import Env Logins
         * @description Move the logins from `backend/.env` into the encrypted store (never over one that is already
         *     stored). `.env` itself is not touched: delete those lines yourself, or use `npm run env:import`.
         *     Needs SECRET_KEY.
         */
        post: operations["import_env_logins_api_v1_settings_env_logins_import_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/signals": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Signals
         * @description Every message the groups sent, newest first, with what became of it and why.
         */
        get: operations["list_signals_api_v1_signals_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/signals/{signal_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Signal */
        get: operations["get_signal_api_v1_signals__signal_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/status": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Status
         * @description The whole picture of the system now: the same data the WebSocket sends first.
         */
        get: operations["get_status_api_v1_status_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/telegram/chats": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Chats
         * @description Groups and channels the logged-in Telegram account is in, by name, marking the ones that
         *     already have a group here. Needs the engine running (it owns the Telegram connection) and
         *     Telegram connected. Private chats are left out: signals come from groups and channels.
         */
        get: operations["list_chats_api_v1_telegram_chats_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/telegram/login": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Login Status
         * @description Where the Telegram login is: logged out, waiting for the code, waiting for the two-step
         *     password, or logged in. Safe to call after a page reload: a half-made login is still here.
         */
        get: operations["login_status_api_v1_telegram_login_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/telegram/login/cancel": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Login Cancel
         * @description Drop a login that is half made.
         */
        post: operations["login_cancel_api_v1_telegram_login_cancel_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/telegram/login/code": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Login Code
         * @description Step 2: the code. The answer says if a password is needed next, or the login is done.
         */
        post: operations["login_code_api_v1_telegram_login_code_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/telegram/login/password": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Login Password
         * @description Step 3, only for an account with two-step verification.
         */
        post: operations["login_password_api_v1_telegram_login_password_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/telegram/login/resend": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Login Resend
         * @description Ask Telegram to send the same code another way (SMS, a call).
         */
        post: operations["login_resend_api_v1_telegram_login_resend_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/telegram/login/start": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Login Start
         * @description Step 1: Telegram sends a code to this number. Needs the API id and hash stored first, and
         *     the engine stopped.
         */
        post: operations["login_start_api_v1_telegram_login_start_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/telegram/logout": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Logout
         * @description Forget the Telegram login (and end it on Telegram's side if it can be reached). Needs the
         *     engine stopped.
         */
        post: operations["logout_api_v1_telegram_logout_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/trades": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Trades
         * @description Newest first.
         */
        get: operations["list_trades_api_v1_trades_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/trades/{trade_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Trade */
        get: operations["get_trade_api_v1_trades__trade_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
}
export type webhooks = Record<string, never>;
export interface components {
    schemas: {
        /** AccountChangedMessage */
        AccountChangedMessage: {
            /**
             * At
             * Format: date-time
             */
            at: string;
            data: components["schemas"]["AccountEventOut"];
            /**
             * Seq
             * @description Number of the latest event this message includes.
             */
            seq: number;
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            type: "account.changed";
        };
        /** AccountEventOut */
        AccountEventOut: {
            account_type: components["schemas"]["AccountType"];
        };
        /** AccountIn */
        AccountIn: {
            account_type: components["schemas"]["AccountType"];
            /**
             * Password
             * @description The owner's password: required to switch to REAL, not to go back to demo.
             */
            password?: string | null;
        };
        /** AccountOut */
        AccountOut: {
            account_type: components["schemas"]["AccountType"];
            /** Real Trading Allowed */
            real_trading_allowed: boolean;
        };
        /**
         * AccountType
         * @enum {string}
         */
        AccountType: "demo" | "real";
        /**
         * AssetSuffixMode
         * @enum {string}
         */
        AssetSuffixMode: "otc" | "none" | "auto";
        /**
         * AuthStateOut
         * @description What the dashboard needs to decide which page to show first.
         */
        AuthStateOut: {
            /** Authenticated */
            authenticated: boolean;
            /** Setup Required */
            setup_required: boolean;
            user?: components["schemas"]["UserOut"] | null;
        };
        /** BalanceOut */
        BalanceOut: {
            account_type: components["schemas"]["AccountType"];
            /** Balance */
            balance: string;
            /**
             * Taken At
             * Format: date-time
             */
            taken_at: string;
        };
        /** BalanceUpdatedMessage */
        BalanceUpdatedMessage: {
            /**
             * At
             * Format: date-time
             */
            at: string;
            data: components["schemas"]["BalanceOut"];
            /**
             * Seq
             * @description Number of the latest event this message includes.
             */
            seq: number;
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            type: "balance.updated";
        };
        /**
         * BreakdownKind
         * @enum {string}
         */
        BreakdownKind: "group" | "asset" | "strategy" | "hour" | "weekday";
        /** BreakdownOut */
        BreakdownOut: {
            by: components["schemas"]["BreakdownKind"];
            filter: components["schemas"]["FilterOut"];
            /** Rows */
            rows: components["schemas"]["BreakdownRowOut"][];
        };
        /** BreakdownRowOut */
        BreakdownRowOut: {
            /** Key */
            key: string;
            /** Label */
            label: string;
            metrics: components["schemas"]["MetricsOut"];
        };
        /** ChainAdvancedMessage */
        ChainAdvancedMessage: {
            /**
             * At
             * Format: date-time
             */
            at: string;
            data: components["schemas"]["ChainOut"];
            /**
             * Seq
             * @description Number of the latest event this message includes.
             */
            seq: number;
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            type: "chain.advanced";
        };
        /** ChainControlOut */
        ChainControlOut: {
            chain: components["schemas"]["ChainOut"];
            /** Stop Requested */
            stop_requested: boolean;
        };
        /** ChainDetailOut */
        ChainDetailOut: {
            chain: components["schemas"]["ChainOut"];
            signal: components["schemas"]["SignalOut"] | null;
            /** Trades */
            trades: components["schemas"]["TradeOut"][];
        };
        /** ChainEndedMessage */
        ChainEndedMessage: {
            /**
             * At
             * Format: date-time
             */
            at: string;
            data: components["schemas"]["ChainOut"];
            /**
             * Seq
             * @description Number of the latest event this message includes.
             */
            seq: number;
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            type: "chain.ended";
        };
        /** ChainOut */
        ChainOut: {
            account_type: components["schemas"]["AccountType"];
            /** Asset */
            asset: string;
            /** Base Stake */
            base_stake: string;
            /** Consecutive Losses */
            consecutive_losses: number;
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /** Duration S */
            duration_s: number;
            /** End Reason */
            end_reason: string | null;
            /** Ended At */
            ended_at: string | null;
            /** Group Id */
            group_id: number;
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /** Max Steps */
            max_steps: number;
            /** Multipliers */
            multipliers: string[];
            origin_direction: components["schemas"]["Direction"];
            /** Signal Id */
            signal_id: string | null;
            status: components["schemas"]["ChainStatus"];
            /** Step */
            step: number;
            strategy: components["schemas"]["Strategy"];
            /**
             * Updated At
             * Format: date-time
             */
            updated_at: string;
        };
        /** ChainStartedMessage */
        ChainStartedMessage: {
            /**
             * At
             * Format: date-time
             */
            at: string;
            data: components["schemas"]["ChainOut"];
            /**
             * Seq
             * @description Number of the latest event this message includes.
             */
            seq: number;
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            type: "chain.started";
        };
        /**
         * ChainStatus
         * @enum {string}
         */
        ChainStatus: "pending" | "open" | "completed" | "exhausted" | "stopped" | "failed" | "unknown";
        /** ChatOut */
        ChatOut: {
            /**
             * Added
             * @description A group for this chat already exists.
             */
            added: boolean;
            /**
             * Chat Id
             * @description What a group's `telegram_chat_id` must be.
             */
            chat_id: number;
            /**
             * Kind
             * @enum {string}
             */
            kind: "group" | "channel";
            /** Title */
            title: string;
        };
        /** ChatsOut */
        ChatsOut: {
            /** Items */
            items: components["schemas"]["ChatOut"][];
        };
        /**
         * ClientMessage
         * @description The only message a client may send on /ws.
         */
        ClientMessage: components["schemas"]["ResyncRequest"];
        /** CodeIn */
        CodeIn: {
            /** Code */
            code: string;
        };
        /** ConnectionChangedMessage */
        ConnectionChangedMessage: {
            /**
             * At
             * Format: date-time
             */
            at: string;
            data: components["schemas"]["ConnectionEventOut"];
            /**
             * Seq
             * @description Number of the latest event this message includes.
             */
            seq: number;
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            type: "connection.changed";
        };
        /** ConnectionEventOut */
        ConnectionEventOut: {
            /** Component */
            component: string;
            /** Connected */
            connected: boolean;
            /** Detail */
            detail: string | null;
        };
        /** ConnectionOut */
        ConnectionOut: {
            /** Connected */
            connected: boolean;
            /** Detail */
            detail: string | null;
            /**
             * Since
             * Format: date-time
             */
            since: string;
        };
        /** ControlsChangedMessage */
        ControlsChangedMessage: {
            /**
             * At
             * Format: date-time
             */
            at: string;
            data: components["schemas"]["ControlsOut"];
            /**
             * Seq
             * @description Number of the latest event this message includes.
             */
            seq: number;
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            type: "controls.changed";
        };
        /** ControlsOut */
        ControlsOut: {
            /** Group Limits */
            group_limits: {
                [key: string]: components["schemas"]["GroupRiskLimitsOut"];
            };
            /** Kill Switch */
            kill_switch: boolean;
            limits: components["schemas"]["RiskLimitsOut"];
            /** Paused Groups */
            paused_groups: number[];
        };
        /**
         * DayOut
         * @description The day the daily limits count, for the account in use.
         */
        DayOut: {
            account_type: components["schemas"]["AccountType"];
            /**
             * Pnl
             * @description Net result since `since`; negative is a loss.
             */
            pnl: string;
            /**
             * Since
             * Format: date-time
             */
            since: string;
        };
        /**
         * Delimiter
         * @enum {string}
         */
        Delimiter: "comma" | "semicolon";
        /** DepthOut */
        DepthOut: {
            /** Avg Chain Profit */
            avg_chain_profit: string | null;
            /** Chains */
            chains: number;
            /** Completed */
            completed: number;
            /** Exhausted */
            exhausted: number;
            filter: components["schemas"]["FilterOut"];
            /** Other */
            other: number;
            /** Steps */
            steps: components["schemas"]["DepthRowOut"][];
        };
        /** DepthRowOut */
        DepthRowOut: {
            /** Chain Profit Ending Here */
            chain_profit_ending_here: string;
            /** Chains Ending Here */
            chains_ending_here: number;
            /** Chains Reaching */
            chains_reaching: number;
            /** Chains Won Here */
            chains_won_here: number;
            /** Losses */
            losses: number;
            /** Profit */
            profit: string;
            /** Share Of Chains */
            share_of_chains: number;
            /** Staked */
            staked: string;
            /**
             * Step
             * @description Trade number in the chain; 1 is the original signal's trade.
             */
            step: number;
            /** Trades */
            trades: number;
            /** Wins */
            wins: number;
        };
        /**
         * Direction
         * @enum {string}
         */
        Direction: "call" | "put";
        /** DrawdownOut */
        DrawdownOut: {
            /** Current Amount */
            current_amount: string;
            /** Max Amount */
            max_amount: string;
            /**
             * Peak Day
             * @description Null when the high point was the start of the range.
             */
            peak_day: string | null;
            /** Trough Day */
            trough_day: string | null;
        };
        /** EngineOut */
        EngineOut: {
            /**
             * Desired
             * @description It is started again when the application starts.
             */
            desired: boolean;
            /**
             * Error
             * @description Why the last start failed, in words.
             */
            error: string | null;
            /**
             * Logins
             * @description The logins it would use, never their values.
             */
            logins: components["schemas"]["LoginItemOut"][];
            /** Missing Logins */
            missing_logins: string[];
            /** Real Trading Allowed */
            real_trading_allowed: boolean;
            /** Since */
            since: string | null;
            /**
             * State
             * @enum {string}
             */
            state: "stopped" | "starting" | "running" | "stopping" | "failed";
        };
        /** EngineStatus */
        EngineStatus: {
            /** Enabled */
            enabled: boolean;
            /**
             * Error
             * @default null
             */
            error: string | null;
            /** Running */
            running: boolean;
            /**
             * State
             * @default stopped
             * @enum {string}
             */
            state: "stopped" | "starting" | "running" | "stopping" | "failed";
        };
        /** EnvImportOut */
        EnvImportOut: {
            /**
             * Imported
             * @description The logins moved just now.
             */
            imported: string[];
            /** Items */
            items: components["schemas"]["EnvLoginOut"][];
        };
        /** EnvLoginOut */
        EnvLoginOut: {
            /**
             * In Env
             * @description backend/.env still has a value for it.
             */
            in_env: boolean;
            /** Label */
            label: string;
            /**
             * Stored
             * @description The encrypted store has one (it wins over .env).
             */
            stored: boolean;
        };
        /** EnvLoginsOut */
        EnvLoginsOut: {
            /** Items */
            items: components["schemas"]["EnvLoginOut"][];
        };
        /** EquityOut */
        EquityOut: {
            filter: components["schemas"]["FilterOut"];
            /** Points */
            points: components["schemas"]["EquityPointOut"][];
        };
        /** EquityPointOut */
        EquityPointOut: {
            /** Cumulative */
            cumulative: string;
            /** Day */
            day: string;
            /** Profit */
            profit: string;
            /** Trades */
            trades: number;
        };
        /** ErrorBody */
        ErrorBody: {
            error: components["schemas"]["ErrorDetail"];
        };
        /**
         * ErrorDetail
         * @description `code` is stable and meant for programs; `message` is for the owner to read.
         */
        ErrorDetail: {
            /** Code */
            code: string;
            /** Details */
            details?: components["schemas"]["FieldProblem"][] | {
                [key: string]: unknown;
            } | null;
            /** Message */
            message: string;
        };
        /** ExpectationOut */
        ExpectationOut: {
            /** Actual Win Rate */
            actual_win_rate: number | null;
            /** Breakeven Win Rate */
            breakeven_win_rate: number | null;
            /** Edge */
            edge: number | null;
            /**
             * Verdict
             * @enum {string}
             */
            verdict: "not_enough_data" | "consistent_with_break_even" | "above_break_even" | "below_break_even";
            /** Z Score */
            z_score: number | null;
        };
        /** FieldProblem */
        FieldProblem: {
            /** Field */
            field: string;
            /** Message */
            message: string;
        };
        /**
         * FilterOut
         * @description The filters the numbers below were computed with, echoed back.
         */
        FilterOut: {
            account_type: components["schemas"]["AccountType"];
            /** Asset */
            asset: string | null;
            /** Group Id */
            group_id: number | null;
            /** Since */
            since: string | null;
            strategy: components["schemas"]["Strategy"] | null;
            /** Until */
            until: string | null;
            /** Utc Offset Minutes */
            utc_offset_minutes: number;
        };
        /** GroupCreateIn */
        GroupCreateIn: {
            /**
             * Enabled
             * @default true
             */
            enabled: boolean;
            settings: components["schemas"]["GroupSettingsIn"];
            /**
             * Telegram Chat Id
             * @description Find it with `npm run telegram:dialogs`.
             */
            telegram_chat_id: number;
            /** Title */
            title: string;
        };
        /** GroupOut */
        GroupOut: {
            /** Active Chains */
            active_chains: number;
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /** Enabled */
            enabled: boolean;
            /** Id */
            id: number;
            /** Paused */
            paused: boolean;
            settings: components["schemas"]["GroupSettingsOut"] | null;
            /** Telegram Chat Id */
            telegram_chat_id: number;
            /** Title */
            title: string;
            /**
             * Updated At
             * Format: date-time
             */
            updated_at: string;
        };
        /**
         * GroupRiskLimitsIn
         * @description Limits of one group, on top of the global ones. Leave a field out (null) for no limit.
         */
        GroupRiskLimitsIn: {
            /** Daily Profit Target */
            daily_profit_target?: number | string | null;
            /** Daily Stop Loss */
            daily_stop_loss?: number | string | null;
            /** Max Stake */
            max_stake?: number | string | null;
        };
        /** GroupRiskLimitsOut */
        GroupRiskLimitsOut: {
            /** Daily Profit Target */
            daily_profit_target: string | null;
            /** Daily Stop Loss */
            daily_stop_loss: string | null;
            /** Max Stake */
            max_stake: string | null;
        };
        /**
         * GroupSettingsIn
         * @description docs/DOMAIN.md section 5. There must be exactly one multiplier per step.
         */
        GroupSettingsIn: {
            asset_suffix_mode: components["schemas"]["AssetSuffixMode"];
            /** Base Stake */
            base_stake: number | string;
            /** Max Steps */
            max_steps: number;
            /**
             * Min Payout Pct
             * @default 0
             */
            min_payout_pct: number;
            /** Multipliers */
            multipliers?: (number | string)[];
            /**
             * Parser
             * @default legacy_v1
             */
            parser: string;
            strategy: components["schemas"]["Strategy"];
            /**
             * Timezone
             * @description `UTC-3`, `UTC+5:30` or an IANA zone name.
             */
            timezone: string;
        };
        /** GroupSettingsOut */
        GroupSettingsOut: {
            asset_suffix_mode: components["schemas"]["AssetSuffixMode"];
            /** Base Stake */
            base_stake: string;
            /** Max Steps */
            max_steps: number;
            /** Min Payout Pct */
            min_payout_pct: number;
            /** Multipliers */
            multipliers: string[];
            /** Parser */
            parser: string;
            strategy: components["schemas"]["Strategy"];
            /** Timezone */
            timezone: string;
            /**
             * Updated At
             * Format: date-time
             */
            updated_at: string;
        };
        /**
         * GroupUpdateIn
         * @description Replaces the group's title, enabled flag and settings. The chat cannot be changed: that
         *     would be a different group.
         */
        GroupUpdateIn: {
            /** Enabled */
            enabled: boolean;
            settings: components["schemas"]["GroupSettingsIn"];
            /** Title */
            title: string;
        };
        /** HealthResponse */
        HealthResponse: {
            /** Background Tasks */
            background_tasks: number;
            /**
             * Database
             * @enum {string}
             */
            database: "ok" | "unavailable";
            engine: components["schemas"]["EngineStatus"];
            /** Environment */
            environment: string;
            /** Events Published */
            events_published: number;
            /** Last Event At */
            last_event_at?: string | null;
            /**
             * Problems
             * @default []
             */
            problems: string[];
            quotex?: components["schemas"]["ConnectionOut"] | null;
            /**
             * Status
             * @enum {string}
             */
            status: "ok" | "degraded";
            telegram?: components["schemas"]["ConnectionOut"] | null;
            /** Version */
            version: string;
            writer: components["schemas"]["WriterHealth"] | null;
            /**
             * Ws Clients
             * @default 0
             */
            ws_clients: number;
        };
        /** HeartbeatMessage */
        HeartbeatMessage: {
            /**
             * At
             * Format: date-time
             */
            at: string;
            /**
             * Seq
             * @description Number of the latest event this message includes.
             */
            seq: number;
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            type: "heartbeat";
        };
        /** KillSwitchIn */
        KillSwitchIn: {
            /**
             * Stop Chains
             * @description Also end the running chains now (their open trades still settle).
             * @default false
             */
            stop_chains: boolean;
        };
        /** LoginIn */
        LoginIn: {
            /** Password */
            password: string;
            /** Username */
            username: string;
        };
        /** LoginItemOut */
        LoginItemOut: {
            /** Label */
            label: string;
            /** Present */
            present: boolean;
            /**
             * Required
             * @description The engine cannot start without it.
             */
            required: boolean;
            /**
             * Source
             * @enum {string}
             */
            source: "dashboard" | ".env" | ".session file" | "missing" | "unreadable";
        };
        /**
         * LoginStatusOut
         * @description Where the Telegram login is. Never the login itself.
         */
        LoginStatusOut: {
            /**
             * Configured
             * @description The API id and hash are stored, so a login can begin.
             */
            configured: boolean;
            /**
             * Delivery
             * @description Where Telegram says it sent the code, in words.
             */
            delivery: string | null;
            /**
             * Engine Running
             * @description Logging in or out needs the engine stopped.
             */
            engine_running: boolean;
            /**
             * Phone Hint
             * @description The phone number with its middle hidden.
             */
            phone_hint: string | null;
            /**
             * Problem
             * @description Why a stored login cannot be used.
             */
            problem: string | null;
            /**
             * Resends Left
             * @description How many more times the code can be sent another way.
             */
            resends_left: number;
            /**
             * State
             * @enum {string}
             */
            state: "logged_out" | "code_sent" | "password_needed" | "logged_in";
        };
        /** MetricsOut */
        MetricsOut: {
            /** Avg Payout Pct */
            avg_payout_pct: number | null;
            /** Avg Stake */
            avg_stake: string | null;
            /** Draws */
            draws: number;
            /** Losses */
            losses: number;
            /**
             * Profit
             * @description Net result; negative is a loss.
             */
            profit: string;
            /**
             * Roi
             * @description profit / staked; null when nothing was staked.
             */
            roi: number | null;
            /**
             * Sample
             * @description How much to trust the numbers: tiny (< 10 trades), small (< 30), ok.
             * @enum {string}
             */
            sample: "tiny" | "small" | "ok";
            /**
             * Staked
             * @description Total stake of these trades.
             */
            staked: string;
            /**
             * Trades
             * @description Trades with a known result.
             */
            trades: number;
            /**
             * Win Rate
             * @description wins / trades, 0 to 1; null with no trades.
             */
            win_rate: number | null;
            /** Wins */
            wins: number;
        };
        /** NotCountedOut */
        NotCountedOut: {
            /** Failed */
            failed: number;
            /** Open */
            open: number;
            /** Unknown */
            unknown: number;
        };
        /** Page[ChainOut] */
        Page_ChainOut_: {
            /** Items */
            items: components["schemas"]["ChainOut"][];
            /** Limit */
            limit: number;
            /** Offset */
            offset: number;
            /** Total */
            total: number;
        };
        /** Page[GroupOut] */
        Page_GroupOut_: {
            /** Items */
            items: components["schemas"]["GroupOut"][];
            /** Limit */
            limit: number;
            /** Offset */
            offset: number;
            /** Total */
            total: number;
        };
        /** Page[RiskEventOut] */
        Page_RiskEventOut_: {
            /** Items */
            items: components["schemas"]["RiskEventOut"][];
            /** Limit */
            limit: number;
            /** Offset */
            offset: number;
            /** Total */
            total: number;
        };
        /** Page[SignalOut] */
        Page_SignalOut_: {
            /** Items */
            items: components["schemas"]["SignalOut"][];
            /** Limit */
            limit: number;
            /** Offset */
            offset: number;
            /** Total */
            total: number;
        };
        /** Page[TradeOut] */
        Page_TradeOut_: {
            /** Items */
            items: components["schemas"]["TradeOut"][];
            /** Limit */
            limit: number;
            /** Offset */
            offset: number;
            /** Total */
            total: number;
        };
        /** PasswordChangeIn */
        PasswordChangeIn: {
            /** Current Password */
            current_password: string;
            /** New Password */
            new_password: string;
        };
        /** PhoneIn */
        PhoneIn: {
            /**
             * Phone
             * @description International format.
             */
            phone: string;
        };
        /** PinIn */
        PinIn: {
            /**
             * Pin
             * @description The digits Quotex e-mailed.
             */
            pin: string;
        };
        /** QuotexLoginOut */
        QuotexLoginOut: {
            /**
             * Configured
             * @description An email and a password are stored, so a login can begin.
             */
            configured: boolean;
            /**
             * Engine Running
             * @description Logging in or out needs the engine stopped.
             */
            engine_running: boolean;
            /**
             * Message
             * @description Why the last login did not work, in words.
             */
            message: string | null;
            /**
             * Pin Prompt
             * @description What Quotex asks for, in its own words.
             */
            pin_prompt: string | null;
            /**
             * State
             * @enum {string}
             */
            state: "logged_out" | "working" | "pin_needed" | "logged_in";
        };
        /** RealTradingIn */
        RealTradingIn: {
            /** Allowed */
            allowed: boolean;
            /**
             * Password
             * @description The owner's own password.
             */
            password: string;
        };
        /**
         * ResyncRequest
         * @description The only message a client may send.
         */
        ResyncRequest: {
            /**
             * Type
             * @constant
             */
            type: "resync";
        };
        /** RiskEventOut */
        RiskEventOut: {
            /** Details */
            details: {
                [key: string]: unknown;
            } | null;
            /** Group Id */
            group_id: number | null;
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /** Kind */
            kind: string;
            /** Message */
            message: string;
            /**
             * Occurred At
             * Format: date-time
             */
            occurred_at: string;
        };
        /**
         * RiskLimitsIn
         * @description The global limits. Null means no limit. Reaching `max_*` is allowed, exceeding it is not;
         *     reaching the daily stop-loss or profit target ends trading for the day (decision D-37).
         */
        RiskLimitsIn: {
            /** Daily Profit Target */
            daily_profit_target?: number | string | null;
            /** Daily Stop Loss */
            daily_stop_loss?: number | string | null;
            /** Max Chain Trades */
            max_chain_trades?: number | null;
            /** Max Concurrent Trades */
            max_concurrent_trades?: number | null;
            /** Max Exposure */
            max_exposure?: number | string | null;
            /** Max Stake */
            max_stake?: number | string | null;
            /**
             * Reset Time
             * Format: time
             * @default 00:00:00
             */
            reset_time: string;
            /**
             * Reset Timezone
             * @default UTC
             */
            reset_timezone: string;
        };
        /** RiskLimitsOut */
        RiskLimitsOut: {
            /** Daily Profit Target */
            daily_profit_target: string | null;
            /** Daily Stop Loss */
            daily_stop_loss: string | null;
            /** Max Chain Trades */
            max_chain_trades: number | null;
            /** Max Concurrent Trades */
            max_concurrent_trades: number | null;
            /** Max Exposure */
            max_exposure: string | null;
            /** Max Stake */
            max_stake: string | null;
            /**
             * Reset Time
             * @description HH:MM in `reset_timezone`.
             */
            reset_time: string;
            /** Reset Timezone */
            reset_timezone: string;
        };
        /** RiskOut */
        RiskOut: {
            controls: components["schemas"]["ControlsOut"];
            /** @description Null while the engine is not running. */
            day: components["schemas"]["DayOut"] | null;
            /** Open Exposure */
            open_exposure: string | null;
            /** Open Trades */
            open_trades: number | null;
        };
        /** RiskTrippedMessage */
        RiskTrippedMessage: {
            /**
             * At
             * Format: date-time
             */
            at: string;
            data: components["schemas"]["RiskEventOut"];
            /**
             * Seq
             * @description Number of the latest event this message includes.
             */
            seq: number;
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            type: "risk.tripped";
        };
        /** SampleGuideOut */
        SampleGuideOut: {
            /**
             * Small Below
             * @default 30
             */
            small_below: number;
            /**
             * Tiny Below
             * @default 10
             */
            tiny_below: number;
        };
        /** SecretIn */
        SecretIn: {
            /** Value */
            value: string;
        };
        /** SecretItemOut */
        SecretItemOut: {
            /**
             * Group
             * @enum {string}
             */
            group: "logins" | "telegram";
            /** Help */
            help: string;
            /** Is Set */
            is_set: boolean;
            /** Label */
            label: string;
            /** Name */
            name: string;
            /** Readable */
            readable: boolean;
            /** Updated At */
            updated_at: string | null;
        };
        /** SecretsOut */
        SecretsOut: {
            /** Items */
            items: components["schemas"]["SecretItemOut"][];
            /**
             * Key
             * @enum {string}
             */
            key: "ok" | "missing" | "invalid";
        };
        /**
         * ServerMessage
         * @description Every message the server can send on /ws; see app/api/schemas/ws.py.
         */
        ServerMessage: components["schemas"]["SnapshotMessage"] | components["schemas"]["HeartbeatMessage"] | components["schemas"]["SignalReceivedMessage"] | components["schemas"]["ChainStartedMessage"] | components["schemas"]["ChainAdvancedMessage"] | components["schemas"]["ChainEndedMessage"] | components["schemas"]["TradeOpenedMessage"] | components["schemas"]["TradeSettledMessage"] | components["schemas"]["RiskTrippedMessage"] | components["schemas"]["BalanceUpdatedMessage"] | components["schemas"]["ConnectionChangedMessage"] | components["schemas"]["AccountChangedMessage"] | components["schemas"]["ControlsChangedMessage"];
        /** SettingItemOut */
        SettingItemOut: {
            /** Choices */
            choices: string[];
            /** Default Value */
            default_value: string;
            /** Help */
            help: string;
            /** Key */
            key: string;
            /**
             * Kind
             * @enum {string}
             */
            kind: "choice" | "text";
            /** Label */
            label: string;
            /**
             * Source
             * @enum {string}
             */
            source: "database" | "environment" | "default";
            /** Value */
            value: string;
        };
        /**
         * SettingsIn
         * @description `null` for a key removes the stored value (back to `.env` or the default).
         */
        SettingsIn: {
            /** Values */
            values: {
                [key: string]: string | null;
            };
        };
        /** SettingsOut */
        SettingsOut: {
            /** Apply Note */
            apply_note: string;
            /** Items */
            items: components["schemas"]["SettingItemOut"][];
        };
        /** SetupIn */
        SetupIn: {
            /** Password */
            password: string;
            /** Setup Code */
            setup_code: string;
            /** Username */
            username: string;
        };
        /**
         * SignalOut
         * @description `raw_text` is untrusted Telegram text: show it as plain text, never as HTML.
         */
        SignalOut: {
            /** Asset */
            asset: string | null;
            direction: components["schemas"]["Direction"] | null;
            /** Duration S */
            duration_s: number | null;
            /** Entry Time */
            entry_time: string | null;
            /** Group Id */
            group_id: number;
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /** Raw Text */
            raw_text: string;
            /** Reason */
            reason: string | null;
            /**
             * Received At
             * Format: date-time
             */
            received_at: string;
            status: components["schemas"]["SignalStatus"];
            /** Telegram Message Id */
            telegram_message_id: number | null;
        };
        /** SignalReceivedMessage */
        SignalReceivedMessage: {
            /**
             * At
             * Format: date-time
             */
            at: string;
            data: components["schemas"]["SignalOut"];
            /**
             * Seq
             * @description Number of the latest event this message includes.
             */
            seq: number;
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            type: "signal.received";
        };
        /**
         * SignalStatus
         * @enum {string}
         */
        SignalStatus: "parsed" | "not_parsed" | "ignored";
        /** SnapshotMessage */
        SnapshotMessage: {
            /**
             * At
             * Format: date-time
             */
            at: string;
            data: components["schemas"]["SnapshotOut"];
            /**
             * Reason
             * @enum {string}
             */
            reason: "connect" | "resync" | "slow_consumer";
            /**
             * Seq
             * @description Number of the latest event this message includes.
             */
            seq: number;
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            type: "snapshot";
        };
        /** SnapshotOut */
        SnapshotOut: {
            account_type: components["schemas"]["AccountType"];
            balance: components["schemas"]["BalanceOut"] | null;
            /** Connections */
            connections: {
                [key: string]: components["schemas"]["ConnectionOut"];
            };
            controls: components["schemas"]["ControlsOut"];
            day: components["schemas"]["DayOut"] | null;
            engine: components["schemas"]["EngineStatus"];
            /** Environment */
            environment: string;
            /** Last Event At */
            last_event_at: string | null;
            /** Open Chains */
            open_chains: components["schemas"]["ChainOut"][];
            /** Open Trades */
            open_trades: components["schemas"]["TradeOut"][];
            /** Real Trading Allowed */
            real_trading_allowed: boolean;
            /** Version */
            version: string;
        };
        /**
         * Strategy
         * @enum {string}
         */
        Strategy: "no_martingale" | "martingale" | "flip_every_loss" | "two_step_flip";
        /** StreaksOut */
        StreaksOut: {
            /**
             * Current
             * @description Wins in a row now (positive) or losses in a row (negative).
             */
            current: number;
            /** Longest Loss */
            longest_loss: number;
            /** Longest Win */
            longest_win: number;
        };
        /** SummaryOut */
        SummaryOut: {
            drawdown: components["schemas"]["DrawdownOut"];
            expectation: components["schemas"]["ExpectationOut"];
            filter: components["schemas"]["FilterOut"];
            /** First Day */
            first_day: string | null;
            /** Last Day */
            last_day: string | null;
            metrics: components["schemas"]["MetricsOut"];
            not_counted: components["schemas"]["NotCountedOut"];
            sample_guide: components["schemas"]["SampleGuideOut"];
            streaks: components["schemas"]["StreaksOut"];
        };
        /** TelegramPasswordIn */
        TelegramPasswordIn: {
            /**
             * Password
             * @description Two-step verification.
             */
            password: string;
        };
        /**
         * TradeLatency
         * @description Milliseconds between the steps of the hot path (docs/ARCHITECTURE.md section 4). A field is
         *     null when the trade does not have both of its stamps (follow-ups have no Telegram message).
         */
        TradeLatency: {
            /** Decision To Order Ms */
            decision_to_order_ms: number | null;
            /** Order Ack Ms */
            order_ack_ms: number | null;
            /** Signal To Order Ms */
            signal_to_order_ms: number | null;
        };
        /** TradeOpenedMessage */
        TradeOpenedMessage: {
            /**
             * At
             * Format: date-time
             */
            at: string;
            data: components["schemas"]["TradeOut"];
            /**
             * Seq
             * @description Number of the latest event this message includes.
             */
            seq: number;
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            type: "trade.opened";
        };
        /** TradeOut */
        TradeOut: {
            account_type: components["schemas"]["AccountType"];
            /** Asset */
            asset: string;
            /** Broker Order Id */
            broker_order_id: string | null;
            /**
             * Chain Id
             * Format: uuid
             */
            chain_id: string;
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            direction: components["schemas"]["Direction"];
            /** Duration S */
            duration_s: number;
            /** Error */
            error: string | null;
            /** Expires At */
            expires_at: string | null;
            /** Group Id */
            group_id: number;
            /**
             * Id
             * Format: uuid
             */
            id: string;
            latency: components["schemas"]["TradeLatency"];
            /** Opened At */
            opened_at: string | null;
            /** Payout Pct */
            payout_pct: number | null;
            /** Profit */
            profit: string | null;
            /** Settled At */
            settled_at: string | null;
            /** Stake */
            stake: string;
            status: components["schemas"]["TradeStatus"];
            /** Step */
            step: number;
        };
        /** TradeSettledMessage */
        TradeSettledMessage: {
            /**
             * At
             * Format: date-time
             */
            at: string;
            data: components["schemas"]["TradeOut"];
            /**
             * Seq
             * @description Number of the latest event this message includes.
             */
            seq: number;
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            type: "trade.settled";
        };
        /**
         * TradeStatus
         * @enum {string}
         */
        TradeStatus: "pending" | "open" | "won" | "lost" | "draw" | "failed" | "unknown";
        /** UserOut */
        UserOut: {
            role: components["schemas"]["UserRole"];
            /** Username */
            username: string;
        };
        /**
         * UserRole
         * @enum {string}
         */
        UserRole: "admin";
        /** WriterHealth */
        WriterHealth: {
            /** Dropped */
            dropped: number;
            /** Failed */
            failed: number;
            /** Queue Depth */
            queue_depth: number;
            /**
             * Retrying
             * @default false
             */
            retrying: boolean;
            /** Written */
            written: number;
        };
    };
    responses: never;
    parameters: never;
    requestBodies: never;
    headers: never;
    pathItems: never;
}
export type $defs = Record<string, never>;
export interface operations {
    get_account_api_v1_account_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AccountOut"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Unprocessable Entity */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Too Many Requests */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Internal Server Error */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
        };
    };
    set_account_api_v1_account_put: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["AccountIn"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AccountOut"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Unprocessable Entity */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Too Many Requests */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Internal Server Error */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
        };
    };
    set_real_trading_api_v1_account_real_trading_put: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["RealTradingIn"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AccountOut"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Unprocessable Entity */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Too Many Requests */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Internal Server Error */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
        };
    };
    login_api_v1_auth_login_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["LoginIn"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["UserOut"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Unprocessable Entity */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Too Many Requests */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Internal Server Error */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
        };
    };
    logout_api_v1_auth_logout_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Unprocessable Entity */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Too Many Requests */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Internal Server Error */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
        };
    };
    change_password_api_v1_auth_password_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["PasswordChangeIn"];
            };
        };
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Unprocessable Entity */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Too Many Requests */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Internal Server Error */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
        };
    };
    setup_api_v1_auth_setup_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["SetupIn"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["UserOut"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Unprocessable Entity */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Too Many Requests */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Internal Server Error */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
        };
    };
    get_state_api_v1_auth_state_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AuthStateOut"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Unprocessable Entity */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Too Many Requests */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Internal Server Error */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
        };
    };
    list_chains_api_v1_chains_get: {
        parameters: {
            query?: {
                group_id?: number | null;
                status?: components["schemas"]["ChainStatus"] | null;
                account_type?: components["schemas"]["AccountType"] | null;
                /** @description Rows per page. */
                limit?: number;
                /** @description Rows to skip. */
                offset?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Page_ChainOut_"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Unprocessable Entity */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Too Many Requests */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Internal Server Error */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
        };
    };
    get_chain_api_v1_chains__chain_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                chain_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ChainDetailOut"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Unprocessable Entity */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Too Many Requests */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Internal Server Error */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
        };
    };
    end_chain_api_v1_chains__chain_id__end_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                chain_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ChainControlOut"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Unprocessable Entity */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Too Many Requests */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Internal Server Error */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
        };
    };
    stop_after_current_api_v1_chains__chain_id__stop_after_current_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                chain_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ChainControlOut"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Unprocessable Entity */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Too Many Requests */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Internal Server Error */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
        };
    };
    get_engine_state_api_v1_engine_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["EngineOut"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Unprocessable Entity */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Too Many Requests */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Internal Server Error */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
        };
    };
    restart_engine_api_v1_engine_restart_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["EngineOut"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Unprocessable Entity */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Too Many Requests */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Internal Server Error */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
        };
    };
    start_engine_api_v1_engine_start_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["EngineOut"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Unprocessable Entity */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Too Many Requests */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Internal Server Error */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
        };
    };
    stop_engine_api_v1_engine_stop_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["EngineOut"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Unprocessable Entity */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Too Many Requests */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Internal Server Error */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
        };
    };
    list_groups_api_v1_groups_get: {
        parameters: {
            query?: {
                /** @description Rows per page. */
                limit?: number;
                /** @description Rows to skip. */
                offset?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Page_GroupOut_"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Unprocessable Entity */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Too Many Requests */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Internal Server Error */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
        };
    };
    create_group_api_v1_groups_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["GroupCreateIn"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["GroupOut"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Unprocessable Entity */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Too Many Requests */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Internal Server Error */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
        };
    };
    get_group_api_v1_groups__group_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                group_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["GroupOut"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Unprocessable Entity */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Too Many Requests */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Internal Server Error */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
        };
    };
    update_group_api_v1_groups__group_id__put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                group_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["GroupUpdateIn"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["GroupOut"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Unprocessable Entity */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Too Many Requests */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Internal Server Error */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
        };
    };
    delete_group_api_v1_groups__group_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                group_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Unprocessable Entity */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Too Many Requests */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Internal Server Error */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
        };
    };
    pause_group_api_v1_groups__group_id__pause_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                group_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["GroupOut"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Unprocessable Entity */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Too Many Requests */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Internal Server Error */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
        };
    };
    resume_group_api_v1_groups__group_id__resume_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                group_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["GroupOut"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Unprocessable Entity */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Too Many Requests */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Internal Server Error */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
        };
    };
    get_group_risk_api_v1_groups__group_id__risk_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                group_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["GroupRiskLimitsOut"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Unprocessable Entity */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Too Many Requests */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Internal Server Error */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
        };
    };
    set_group_risk_api_v1_groups__group_id__risk_put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                group_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["GroupRiskLimitsIn"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["GroupRiskLimitsOut"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Unprocessable Entity */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Too Many Requests */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Internal Server Error */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
        };
    };
    health_api_v1_health_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HealthResponse"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Unprocessable Entity */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Too Many Requests */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Internal Server Error */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
        };
    };
    engage_kill_switch_api_v1_kill_switch_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: {
            content: {
                "application/json": components["schemas"]["KillSwitchIn"] | null;
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ControlsOut"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Unprocessable Entity */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Too Many Requests */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Internal Server Error */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
        };
    };
    release_kill_switch_api_v1_kill_switch_delete: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ControlsOut"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Unprocessable Entity */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Too Many Requests */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Internal Server Error */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
        };
    };
    login_status_api_v1_quotex_login_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["QuotexLoginOut"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Unprocessable Entity */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Too Many Requests */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Internal Server Error */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
        };
    };
    login_cancel_api_v1_quotex_login_cancel_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["QuotexLoginOut"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Unprocessable Entity */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Too Many Requests */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Internal Server Error */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
        };
    };
    login_pin_api_v1_quotex_login_pin_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["PinIn"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["QuotexLoginOut"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Unprocessable Entity */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Too Many Requests */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Internal Server Error */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
        };
    };
    login_start_api_v1_quotex_login_start_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["QuotexLoginOut"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Unprocessable Entity */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Too Many Requests */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Internal Server Error */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
        };
    };
    logout_api_v1_quotex_logout_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["QuotexLoginOut"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Unprocessable Entity */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Too Many Requests */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Internal Server Error */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
        };
    };
    get_breakdown_api_v1_reports_breakdown_get: {
        parameters: {
            query: {
                by: components["schemas"]["BreakdownKind"];
                /** @description Demo and real are never mixed. */
                account_type?: components["schemas"]["AccountType"];
                /** @description Start of the range (inclusive), ISO time with a zone. */
                from?: string | null;
                /** @description End of the range (exclusive), ISO time with a zone. */
                to?: string | null;
                group_id?: number | null;
                strategy?: components["schemas"]["Strategy"] | null;
                asset?: string | null;
                /** @description Your clock for hour of day, weekday and days: minutes from UTC (UTC-3 is -180). A fixed offset: daylight saving is not followed. */
                utc_offset_minutes?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["BreakdownOut"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Unprocessable Entity */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Too Many Requests */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Internal Server Error */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
        };
    };
    get_depth_api_v1_reports_depth_get: {
        parameters: {
            query?: {
                /** @description Demo and real are never mixed. */
                account_type?: components["schemas"]["AccountType"];
                /** @description Start of the range (inclusive), ISO time with a zone. */
                from?: string | null;
                /** @description End of the range (exclusive), ISO time with a zone. */
                to?: string | null;
                group_id?: number | null;
                strategy?: components["schemas"]["Strategy"] | null;
                asset?: string | null;
                /** @description Your clock for hour of day, weekday and days: minutes from UTC (UTC-3 is -180). A fixed offset: daylight saving is not followed. */
                utc_offset_minutes?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DepthOut"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Unprocessable Entity */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Too Many Requests */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Internal Server Error */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
        };
    };
    get_equity_api_v1_reports_equity_get: {
        parameters: {
            query?: {
                /** @description Demo and real are never mixed. */
                account_type?: components["schemas"]["AccountType"];
                /** @description Start of the range (inclusive), ISO time with a zone. */
                from?: string | null;
                /** @description End of the range (exclusive), ISO time with a zone. */
                to?: string | null;
                group_id?: number | null;
                strategy?: components["schemas"]["Strategy"] | null;
                asset?: string | null;
                /** @description Your clock for hour of day, weekday and days: minutes from UTC (UTC-3 is -180). A fixed offset: daylight saving is not followed. */
                utc_offset_minutes?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["EquityOut"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Unprocessable Entity */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Too Many Requests */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Internal Server Error */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
        };
    };
    export_breakdown_csv_api_v1_reports_export_breakdown_csv_get: {
        parameters: {
            query: {
                by: components["schemas"]["BreakdownKind"];
                delimiter?: components["schemas"]["Delimiter"];
                /** @description Demo and real are never mixed. */
                account_type?: components["schemas"]["AccountType"];
                /** @description Start of the range (inclusive), ISO time with a zone. */
                from?: string | null;
                /** @description End of the range (exclusive), ISO time with a zone. */
                to?: string | null;
                group_id?: number | null;
                strategy?: components["schemas"]["Strategy"] | null;
                asset?: string | null;
                /** @description Your clock for hour of day, weekday and days: minutes from UTC (UTC-3 is -180). A fixed offset: daylight saving is not followed. */
                utc_offset_minutes?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description One row per group of trades. */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "text/csv": unknown;
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Unprocessable Entity */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Too Many Requests */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Internal Server Error */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
        };
    };
    export_trades_csv_api_v1_reports_export_trades_csv_get: {
        parameters: {
            query?: {
                /** @description `semicolon` for Excel in many locales. */
                delimiter?: components["schemas"]["Delimiter"];
                /** @description Demo and real are never mixed. */
                account_type?: components["schemas"]["AccountType"];
                /** @description Start of the range (inclusive), ISO time with a zone. */
                from?: string | null;
                /** @description End of the range (exclusive), ISO time with a zone. */
                to?: string | null;
                group_id?: number | null;
                strategy?: components["schemas"]["Strategy"] | null;
                asset?: string | null;
                /** @description Your clock for hour of day, weekday and days: minutes from UTC (UTC-3 is -180). A fixed offset: daylight saving is not followed. */
                utc_offset_minutes?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description One row per trade. */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "text/csv": unknown;
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Unprocessable Entity */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Too Many Requests */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Internal Server Error */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
        };
    };
    get_summary_api_v1_reports_summary_get: {
        parameters: {
            query?: {
                /** @description Demo and real are never mixed. */
                account_type?: components["schemas"]["AccountType"];
                /** @description Start of the range (inclusive), ISO time with a zone. */
                from?: string | null;
                /** @description End of the range (exclusive), ISO time with a zone. */
                to?: string | null;
                group_id?: number | null;
                strategy?: components["schemas"]["Strategy"] | null;
                asset?: string | null;
                /** @description Your clock for hour of day, weekday and days: minutes from UTC (UTC-3 is -180). A fixed offset: daylight saving is not followed. */
                utc_offset_minutes?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SummaryOut"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Unprocessable Entity */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Too Many Requests */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Internal Server Error */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
        };
    };
    get_risk_api_v1_risk_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RiskOut"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Unprocessable Entity */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Too Many Requests */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Internal Server Error */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
        };
    };
    list_risk_events_api_v1_risk_events_get: {
        parameters: {
            query?: {
                /** @description Rows per page. */
                limit?: number;
                /** @description Rows to skip. */
                offset?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Page_RiskEventOut_"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Unprocessable Entity */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Too Many Requests */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Internal Server Error */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
        };
    };
    set_risk_limits_api_v1_risk_limits_put: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["RiskLimitsIn"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RiskLimitsOut"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Unprocessable Entity */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Too Many Requests */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Internal Server Error */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
        };
    };
    get_secrets_api_v1_secrets_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SecretsOut"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Unprocessable Entity */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Too Many Requests */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Internal Server Error */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
        };
    };
    put_secret_api_v1_secrets__name__put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                name: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["SecretIn"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SecretItemOut"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Unprocessable Entity */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Too Many Requests */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Internal Server Error */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
        };
    };
    delete_secret_api_v1_secrets__name__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                name: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Unprocessable Entity */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Too Many Requests */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Internal Server Error */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
        };
    };
    get_settings_api_v1_settings_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SettingsOut"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Unprocessable Entity */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Too Many Requests */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Internal Server Error */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
        };
    };
    put_settings_api_v1_settings_put: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["SettingsIn"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SettingsOut"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Unprocessable Entity */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Too Many Requests */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Internal Server Error */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
        };
    };
    get_env_logins_api_v1_settings_env_logins_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["EnvLoginsOut"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Unprocessable Entity */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Too Many Requests */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Internal Server Error */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
        };
    };
    import_env_logins_api_v1_settings_env_logins_import_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["EnvImportOut"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Unprocessable Entity */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Too Many Requests */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Internal Server Error */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
        };
    };
    list_signals_api_v1_signals_get: {
        parameters: {
            query?: {
                group_id?: number | null;
                status?: components["schemas"]["SignalStatus"] | null;
                /** @description Rows per page. */
                limit?: number;
                /** @description Rows to skip. */
                offset?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Page_SignalOut_"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Unprocessable Entity */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Too Many Requests */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Internal Server Error */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
        };
    };
    get_signal_api_v1_signals__signal_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                signal_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SignalOut"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Unprocessable Entity */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Too Many Requests */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Internal Server Error */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
        };
    };
    get_status_api_v1_status_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SnapshotOut"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Unprocessable Entity */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Too Many Requests */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Internal Server Error */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
        };
    };
    list_chats_api_v1_telegram_chats_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ChatsOut"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Unprocessable Entity */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Too Many Requests */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Internal Server Error */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
        };
    };
    login_status_api_v1_telegram_login_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["LoginStatusOut"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Unprocessable Entity */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Too Many Requests */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Internal Server Error */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
        };
    };
    login_cancel_api_v1_telegram_login_cancel_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["LoginStatusOut"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Unprocessable Entity */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Too Many Requests */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Internal Server Error */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
        };
    };
    login_code_api_v1_telegram_login_code_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CodeIn"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["LoginStatusOut"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Unprocessable Entity */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Too Many Requests */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Internal Server Error */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
        };
    };
    login_password_api_v1_telegram_login_password_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["TelegramPasswordIn"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["LoginStatusOut"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Unprocessable Entity */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Too Many Requests */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Internal Server Error */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
        };
    };
    login_resend_api_v1_telegram_login_resend_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["LoginStatusOut"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Unprocessable Entity */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Too Many Requests */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Internal Server Error */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
        };
    };
    login_start_api_v1_telegram_login_start_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["PhoneIn"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["LoginStatusOut"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Unprocessable Entity */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Too Many Requests */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Internal Server Error */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
        };
    };
    logout_api_v1_telegram_logout_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["LoginStatusOut"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Unprocessable Entity */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Too Many Requests */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Internal Server Error */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
        };
    };
    list_trades_api_v1_trades_get: {
        parameters: {
            query?: {
                group_id?: number | null;
                account_type?: components["schemas"]["AccountType"] | null;
                status?: components["schemas"]["TradeStatus"] | null;
                /** @description Rows per page. */
                limit?: number;
                /** @description Rows to skip. */
                offset?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Page_TradeOut_"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Unprocessable Entity */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Too Many Requests */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Internal Server Error */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
        };
    };
    get_trade_api_v1_trades__trade_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                trade_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TradeOut"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Unprocessable Entity */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Too Many Requests */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Internal Server Error */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
        };
    };
}
