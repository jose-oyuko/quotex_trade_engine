import { useQuery } from '@tanstack/react-query'
import { useId, useState } from 'react'
import { api, ApiError } from '../../api/client'
import type { TelegramChat } from '../../api/types'
import { Button } from '../../components/Button'
import type { PickedChat } from './GroupForm'

/** What to tell the owner when the list cannot be had; they can always type the id instead. */
function problemText(error: unknown): string {
  if (error instanceof ApiError) return error.message
  return error instanceof Error ? error.message : 'Something went wrong.'
}

function kindText(chat: TelegramChat): string {
  return chat.kind === 'group' ? 'group' : 'channel'
}

/**
 * "Choose from my Telegram chats": asks the backend (which asks Telegram) for the chats the logged-in
 * account is in and lets the owner pick one by name. Nothing is requested until the button is
 * pressed, so opening the form never talks to Telegram.
 */
export function TelegramChatPicker({ onPick }: { onPick: (chat: PickedChat) => void }) {
  const [open, setOpen] = useState(false)
  const [search, setSearch] = useState('')
  const searchId = useId()
  const chats = useQuery({
    queryKey: ['telegram', 'chats'],
    queryFn: ({ signal }) => api.telegram.chats(signal),
    enabled: open,
    retry: false,
    staleTime: 0,
    gcTime: 0, // a fresh list every time the panel is opened
  })

  if (!open) {
    return (
      <div className="chat-picker">
        <Button
          onClick={() => {
            setOpen(true)
          }}
        >
          Choose from my Telegram chats
        </Button>
      </div>
    )
  }

  const needle = search.trim().toLowerCase()
  const shown = (chats.data?.items ?? []).filter((c) => c.title.toLowerCase().includes(needle))

  return (
    <div className="chat-picker" aria-label="Your Telegram chats" role="group">
      {chats.isPending && <p role="status">Asking Telegram for your chats…</p>}
      {chats.isError && (
        <>
          <p role="alert" className="form-error">
            {problemText(chats.error)}
          </p>
          <p className="help">You can still type the chat id below.</p>
          <Button onClick={() => void chats.refetch()}>Try again</Button>
        </>
      )}
      {chats.isSuccess && (
        <>
          {chats.data.items.length === 0 ? (
            <p>
              This Telegram account is not in any group or channel. Join the signal group in
              Telegram first.
            </p>
          ) : (
            <>
              <label htmlFor={searchId}>Search your chats</label>
              <input
                id={searchId}
                type="search"
                value={search}
                onChange={(event) => {
                  setSearch(event.target.value)
                }}
              />
              {shown.length === 0 ? (
                <p>No chat matches that.</p>
              ) : (
                <ul className="chat-list">
                  {shown.map((chat) => (
                    <li key={chat.chat_id}>
                      <button
                        type="button"
                        className="chat-choice"
                        disabled={chat.added}
                        onClick={() => {
                          onPick({ chat_id: chat.chat_id, title: chat.title })
                          setOpen(false)
                          setSearch('')
                        }}
                      >
                        <span>{chat.title}</span>
                        <small>
                          {kindText(chat)}
                          {chat.added ? ', already added' : ''}
                        </small>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </>
          )}
        </>
      )}
      <Button
        variant="quiet"
        onClick={() => {
          setOpen(false)
        }}
      >
        Close the list
      </Button>
    </div>
  )
}
