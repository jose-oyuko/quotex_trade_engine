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
         * @description Switch between demo and real. Refused while a chain or trade is running; real also needs
         *     QUOTEX_ALLOW_REAL=true (decision D-15).
         */
        put: operations["set_account_api_v1_account_put"];
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
    "/api/v1/reports/summary": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Reports Summary */
        get: operations["reports_summary_api_v1_reports_summary_get"];
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
        /**
         * ClientMessage
         * @description The only message a client may send on /ws.
         */
        ClientMessage: components["schemas"]["ResyncRequest"];
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
         * Direction
         * @enum {string}
         */
        Direction: "call" | "put";
        /** EngineStatus */
        EngineStatus: {
            /** Enabled */
            enabled: boolean;
            /** Running */
            running: boolean;
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
        /** FieldProblem */
        FieldProblem: {
            /** Field */
            field: string;
            /** Message */
            message: string;
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
            quotex?: components["schemas"]["ConnectionOut"] | null;
            /**
             * Status
             * @constant
             */
            status: "ok";
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
        /**
         * ServerMessage
         * @description Every message the server can send on /ws; see app/api/schemas/ws.py.
         */
        ServerMessage: components["schemas"]["SnapshotMessage"] | components["schemas"]["HeartbeatMessage"] | components["schemas"]["SignalReceivedMessage"] | components["schemas"]["ChainStartedMessage"] | components["schemas"]["ChainAdvancedMessage"] | components["schemas"]["ChainEndedMessage"] | components["schemas"]["TradeOpenedMessage"] | components["schemas"]["TradeSettledMessage"] | components["schemas"]["RiskTrippedMessage"] | components["schemas"]["BalanceUpdatedMessage"] | components["schemas"]["ConnectionChangedMessage"] | components["schemas"]["AccountChangedMessage"] | components["schemas"]["ControlsChangedMessage"];
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
        /** WriterHealth */
        WriterHealth: {
            /** Dropped */
            dropped: number;
            /** Failed */
            failed: number;
            /** Queue Depth */
            queue_depth: number;
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
    reports_summary_api_v1_reports_summary_get: {
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
                    "application/json": unknown;
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
