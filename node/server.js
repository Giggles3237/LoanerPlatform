// Standalone server for the loaner pricing service — mirrors bopchipboard's
// server.js so merging is mechanical: move routes/loanerPricing.js (and
// lib/, seed/) into bopchipboard, add the app.use line there, and retire
// this file along with routes/auth.js (chipboard's own auth takes over).

const express = require('express');
const cors = require('cors');
require('dotenv').config();

const app = express();
const PORT = process.env.PORT || 5000;

app.use(cors({
    origin: ['https://bopchips.netlify.app', 'https://www.bopchips.netlify.app', 'http://localhost:3000', 'http://localhost:5001'],
    credentials: true,
    methods: ['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS'],
    allowedHeaders: ['Content-Type', 'Authorization', 'Origin', 'Accept']
}));
app.use(express.json({ limit: '2mb' }));

const authRoutes = require('./routes/auth');
const loanerPricingRoutes = require('./routes/loanerPricing');

app.use('/api/auth', authRoutes);
app.use('/api/loaner-pricing', loanerPricingRoutes);

app.get('/healthz', (req, res) => res.send('ok'));

app.use((err, req, res, next) => {
  console.error(err.stack);
  res.status(500).json({ message: 'Something broke!' });
});

app.listen(PORT, () => {
  console.log(`Loaner pricing server running on port ${PORT}`);
});

module.exports = app;
