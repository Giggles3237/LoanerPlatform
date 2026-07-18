// JWT auth — copied from bopchipboard's middleware/auth.js conventions so
// chipboard tokens work unchanged (same JWT_SECRET, same req.auth shape).
// requireAdmin implements the agreed rule: settings editing is Admin only.

const jwt = require('jsonwebtoken');

const authenticate = (req, res, next) => {
  try {
    const authHeader = req.headers.authorization;

    if (!authHeader || !authHeader.startsWith('Bearer ')) {
      return res.status(401).json({ message: 'Authentication required' });
    }

    const token = authHeader.split(' ')[1];
    const decoded = jwt.verify(token, process.env.JWT_SECRET);
    req.auth = decoded;
    next();
  } catch (error) {
    return res.status(401).json({ message: 'Invalid token' });
  }
};

const requireAdmin = (req, res, next) => {
  if (req.auth && req.auth.role === 'Admin') {
    return next();
  }
  return res.status(403).json({ message: 'Admin access required' });
};

module.exports = { authenticate, requireAdmin };
