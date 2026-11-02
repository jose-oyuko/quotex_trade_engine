import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { ApiError } from '../../api/client'
import { GroupForm } from './GroupForm'
import { EMPTY_GROUP, type GroupFormValues } from './groupSchema'

const filled: GroupFormValues = { ...EMPTY_GROUP, title: 'Alpha', telegram_chat_id: '-1001' }

function setup(
  initial: GroupFormValues = filled,
  onSubmit: (values: GroupFormValues) => Promise<void> = () => Promise.resolve(),
  mode: 'create' | 'edit' = 'create',
) {
  const submit = vi.fn(onSubmit)
  const cancel = vi.fn()
  const user = userEvent.setup()
  render(<GroupForm initial={initial} mode={mode} onSubmit={submit} onCancel={cancel} />)
  return { user, submit, cancel }
}

const multiplierInputs = () => screen.queryAllByLabelText(/^Multiplier for step/)

async function setSteps(user: ReturnType<typeof userEvent.setup>, steps: string) {
  const input = screen.getByLabelText('Steps')
  await user.clear(input)
  if (steps !== '') await user.type(input, steps)
}

describe('GroupForm: one multiplier per step', () => {
  it('shows one labelled multiplier input for each step', () => {
    setup()
    expect(multiplierInputs()).toHaveLength(3)
    expect(screen.getByLabelText('Multiplier for step 1')).toHaveValue('2.0')
    expect(screen.getByLabelText('Multiplier for step 2')).toHaveValue('2.5')
    expect(screen.getByLabelText('Multiplier for step 3')).toHaveValue('3.0')
  })

  it('adds inputs when the number of steps goes up and removes them when it goes down', async () => {
    const { user } = setup()
    await setSteps(user, '5')
    expect(multiplierInputs()).toHaveLength(5)
    expect(screen.getByLabelText('Multiplier for step 4')).toHaveValue('2.0') // a sensible default
    await setSteps(user, '1')
    expect(multiplierInputs()).toHaveLength(1)
    expect(screen.getByLabelText('Multiplier for step 1')).toHaveValue('2.0') // kept what was typed
    await setSteps(user, '0')
    expect(multiplierInputs()).toHaveLength(0)
  })

  it('keeps the multipliers the owner typed when steps are added', async () => {
    const { user } = setup()
    const first = screen.getByLabelText('Multiplier for step 1')
    await user.clear(first)
    await user.type(first, '4')
    await setSteps(user, '4')
    expect(screen.getByLabelText('Multiplier for step 1')).toHaveValue('4')
    expect(multiplierInputs()).toHaveLength(4)
  })

  it('refuses a multiplier of zero and says which step it is, and does not submit', async () => {
    const { user, submit } = setup()
    const second = screen.getByLabelText('Multiplier for step 2')
    await user.clear(second)
    await user.type(second, '0')
    await user.click(screen.getByRole('button', { name: 'Create group' }))
    expect(await screen.findByText('Must be greater than 0')).toBeInTheDocument()
    expect(second).toHaveAttribute('aria-invalid', 'true')
    expect(screen.getByLabelText('Multiplier for step 1')).not.toHaveAttribute(
      'aria-invalid',
      'true',
    )
    expect(submit).not.toHaveBeenCalled()
  })

  it.each(['', 'abc', '-2', '2,5'])('refuses %j as a multiplier', async (bad) => {
    const { user, submit } = setup()
    const third = screen.getByLabelText('Multiplier for step 3')
    await user.clear(third)
    if (bad !== '') await user.type(third, bad)
    await user.click(screen.getByRole('button', { name: 'Create group' }))
    expect(await screen.findAllByRole('alert')).not.toHaveLength(0)
    expect(third).toHaveAttribute('aria-invalid', 'true')
    expect(submit).not.toHaveBeenCalled()
  })

  it('submits once every multiplier is valid, with one value per step', async () => {
    const { user, submit } = setup()
    const second = screen.getByLabelText('Multiplier for step 2')
    await user.clear(second)
    await user.type(second, '0')
    await user.click(screen.getByRole('button', { name: 'Create group' }))
    await screen.findByText('Must be greater than 0')
    await user.clear(second)
    await user.type(second, '3.5')
    await user.click(screen.getByRole('button', { name: 'Create group' }))
    await waitFor(() => {
      expect(submit).toHaveBeenCalledTimes(1)
    })
    const values = submit.mock.calls[0]?.[0]
    expect(values?.max_steps).toBe(3)
    expect(values?.multipliers.map((m) => m.value)).toEqual(['2.0', '3.5', '3.0'])
  })

  it('has no multipliers for a strategy without follow-ups', async () => {
    const { user, submit } = setup()
    await user.selectOptions(screen.getByLabelText('Strategy'), 'no_martingale')
    expect(multiplierInputs()).toHaveLength(0)
    expect(screen.getByLabelText('Steps')).toBeDisabled()
    expect(screen.getByLabelText('Steps')).toHaveValue(0)
    await user.click(screen.getByRole('button', { name: 'Create group' }))
    await waitFor(() => {
      expect(submit).toHaveBeenCalled()
    })
    expect(submit.mock.calls[0]?.[0]).toMatchObject({ strategy: 'no_martingale', max_steps: 0 })
  })

  it('explains the chosen strategy', async () => {
    const { user } = setup()
    expect(screen.getByText(/same direction is traded again/)).toBeInTheDocument()
    await user.selectOptions(screen.getByLabelText('Strategy'), 'flip_every_loss')
    expect(screen.getByText(/opposite direction is traded/)).toBeInTheDocument()
  })

  it('rejects a number of steps that is not a whole number from 0 to 20', async () => {
    const { user, submit } = setup()
    await setSteps(user, '25')
    await user.click(screen.getByRole('button', { name: 'Create group' }))
    expect(await screen.findByText('At most 20 steps')).toBeInTheDocument()
    expect(submit).not.toHaveBeenCalled()
  })
})

describe('GroupForm: the other fields', () => {
  it('needs a name, a chat id and a valid stake before it submits', async () => {
    const { user, submit } = setup({ ...EMPTY_GROUP, base_stake: '0' })
    await user.click(screen.getByRole('button', { name: 'Create group' }))
    expect(await screen.findByText('Give the group a name')).toBeInTheDocument()
    expect(screen.getByText(/The chat id is a whole number/)).toBeInTheDocument()
    expect(screen.getByText('Must be greater than 0')).toBeInTheDocument()
    expect(submit).not.toHaveBeenCalled()
  })

  it('cannot change the chat of an existing group', () => {
    setup(filled, () => Promise.resolve(), 'edit')
    expect(screen.getByLabelText('Telegram chat id')).toHaveAttribute('readonly')
    expect(screen.getByRole('button', { name: 'Save changes' })).toBeInTheDocument()
  })

  it('cancels without submitting', async () => {
    const { user, submit, cancel } = setup()
    await user.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(cancel).toHaveBeenCalled()
    expect(submit).not.toHaveBeenCalled()
  })

  it('every input has a label', () => {
    setup()
    for (const input of screen.getAllByRole('textbox')) {
      expect(input).toHaveAccessibleName()
    }
    for (const input of screen.getAllByRole('spinbutton')) {
      expect(input).toHaveAccessibleName()
    }
  })
})

describe('GroupForm: what the server says', () => {
  it('shows the server’s complaint about one multiplier on that multiplier', async () => {
    const { user } = setup(filled, () =>
      Promise.reject(
        new ApiError(422, 'validation_error', 'The request is not valid.', [
          { field: 'settings.multipliers.1', message: 'The server disagrees' },
        ]),
      ),
    )
    await user.click(screen.getByRole('button', { name: 'Create group' }))
    const message = await screen.findByText('The server disagrees')
    const field = message.closest('.field')
    expect(field).not.toBeNull()
    expect(within(field as HTMLElement).getByLabelText('Multiplier for step 2')).toBeInTheDocument()
  })

  it('shows a duplicate chat on the chat id', async () => {
    const { user } = setup(filled, () =>
      Promise.reject(new ApiError(409, 'group_exists', 'a group for chat -1001 already exists')),
    )
    await user.click(screen.getByRole('button', { name: 'Create group' }))
    const message = await screen.findByText('a group for chat -1001 already exists')
    expect(message.closest('.field')).toContainElement(screen.getByLabelText('Telegram chat id'))
  })

  it('shows any other failure at the top of the form', async () => {
    const { user } = setup(filled, () => Promise.reject(new Error('Cannot reach the backend.')))
    await user.click(screen.getByRole('button', { name: 'Create group' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Cannot reach the backend.')
  })
})
