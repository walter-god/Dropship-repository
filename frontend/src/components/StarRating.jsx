import React, { useState } from 'react';

export default function StarRating({ value = 0, max = 5, interactive = false, size = 'md', onChange }) {
  const [hovered, setHovered] = useState(0);
  const display = hovered || value;
  const sizeClass = size === 'sm' ? 'star-sm' : size === 'lg' ? 'star-lg' : 'star-md';

  return (
    <div className={`star-rating ${sizeClass}`} aria-label={`Rating: ${value} out of ${max}`}>
      {Array.from({ length: max }, (_, i) => {
        const filled = i < display;
        return (
          <span
            key={i}
            className={`star ${filled ? 'star-filled' : 'star-empty'}`}
            onMouseEnter={() => interactive && setHovered(i + 1)}
            onMouseLeave={() => interactive && setHovered(0)}
            onClick={() => interactive && onChange && onChange(i + 1)}
            style={{ cursor: interactive ? 'pointer' : 'default' }}
          >
            {filled ? '★' : '☆'}
          </span>
        );
      })}
      {value > 0 && <span className="star-value">{Number(value).toFixed(1)}</span>}
    </div>
  );
}
