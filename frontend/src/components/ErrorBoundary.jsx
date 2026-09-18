import React from 'react'

export default class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props)
    this.state = { error: null }
  }

  static getDerivedStateFromError(error) {
    return { error }
  }

  componentDidCatch(error, info) {
    console.error('Attendance tracker render error:', error, info)
  }

  render() {
    if (this.state.error) {
      return (
        <div className="empty" style={{ padding: '2rem' }}>
          <b>Something went wrong while rendering this view.</b>
          <div className="mono" style={{ marginTop: '0.6rem', color: 'var(--muted)' }}>
            {String(this.state.error.message || this.state.error)}
          </div>
          <button className="btn" style={{ marginTop: '1rem' }} onClick={() => this.setState({ error: null })}>
            Try again
          </button>
        </div>
      )
    }
    return this.props.children
  }
}