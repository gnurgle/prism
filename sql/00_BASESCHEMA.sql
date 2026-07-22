PRAGMA foreign_keys = ON;

-- IGP: Item Groupings
CREATE TABLE IF NOT EXISTS IGP (
    ITMGRP TEXT PRIMARY KEY -- Group Name
);

-- GTL: Glass Texture Lookup
CREATE TABLE IF NOT EXISTS GTL (
    GLSTEX TEXT PRIMARY KEY -- Glass Texture
);

-- GSL: Glass Source
CREATE TABLE IF NOT EXISTS GSL (
    GLSOURCE TEXT PRIMARY KEY, -- Source of Glass
    SRCWEB INTEGER,           -- Is web order (0 = False, 1 = True)
    GLSLOGO TEXT,             -- Link to Logo
    GLSNOTE TEXT              -- Note about Source
);

-- VENUE: Venues and Event Schedules
CREATE TABLE IF NOT EXISTS VENUE (
    VENUEID INTEGER PRIMARY KEY AUTOINCREMENT, -- Venue ID
    VENUELOC TEXT,                             -- Venue Location
    VMULTI INTEGER,                            -- Multi-day event? (0/1)
    VSDATE TEXT,                               -- Venue Start Date (YYYY-MM-DD)
    VEDATE TEXT,                               -- Venue End Date (YYYY-MM-DD)
    VM INTEGER,                                -- Monday (0/1)
    VMST TEXT,                                 -- Monday Start Time (HH:MM:SS)
    VMET TEXT,                                 -- Monday End Time (HH:MM:SS)
    VTE INTEGER,                               -- Tuesday (0/1)
    VTST TEXT,                                 -- Tuesday Start Time
    VTET TEXT,                                 -- Tuesday End Time
    VW INTEGER,                                -- Wednesday (0/1)
    VWST TEXT,                                 -- Wednesday Start Time
    VWET TEXT,                                 -- Wednesday End Time
    VR INTEGER,                                -- Thursday (0/1)
    VRST TEXT,                                 -- Thursday Start Time
    VRET TEXT,                                 -- Thursday End Time
    VF INTEGER,                                -- Friday (0/1)
    VFST TEXT,                                 -- Friday Start Time
    VFET TEXT,                                 -- Friday End Time
    VST INTEGER,                               -- Saturday (0/1)
    VSTST TEXT,                                -- Saturday Start Time
    VSTET TEXT,                                -- Saturday End Time
    VSN INTEGER,                               -- Sunday (0/1)
    VSNST TEXT,                                -- Sunday Start Time
    VSNET TEXT                                 -- Sunday End Time
);

-- AUDIT: System Audit Log
CREATE TABLE IF NOT EXISTS AUDIT (
    TRANSID INTEGER PRIMARY KEY AUTOINCREMENT, -- Transaction ID
    TRNOP TEXT CHECK(TRNOP IN ('INSERT', 'UPDATE', 'DELETE')), -- Operation
    TRNOLD TEXT,                               -- Old Data
    TRNNEW TEXT,                               -- New Data
    TRNCOL TEXT,                               -- Column Name
    TRNTBL TEXT,                               -- Table Name
    TRNTS TEXT DEFAULT CURRENT_TIMESTAMP       -- TimeStamp of change
);

-- IVR: Item Variants
CREATE TABLE IF NOT EXISTS IVR (
    VARIID INTEGER PRIMARY KEY AUTOINCREMENT, -- PID of Variant
    ITMVARI TEXT,                             -- Variant Name
    ITMGRP TEXT,                              -- Group name
    FOREIGN KEY (ITMGRP) REFERENCES IGP(ITMGRP) ON DELETE SET NULL ON UPDATE CASCADE
);

-- GSI: Glass Sheet Information
CREATE TABLE IF NOT EXISTS GSI (
    GLASSID INTEGER PRIMARY KEY AUTOINCREMENT, -- PID of Glass
    GLSNAME TEXT,                             -- Name of Glass
    GLSMANF TEXT,                             -- Manufacturer of Glass
    GLSLEN INTEGER,                           -- Glass Length
    GLSWID INTEGER,                           -- Glass Width
    GLSTHK INTEGER,                           -- Thickness
    GLSTEX TEXT,                              -- Glass Texture
    GLSIRI INTEGER,                           -- Iridescent (0/1)
    GLSOPAL INTEGER,                          -- Opalescent (0/1)
    GLSOURCE TEXT,                            -- Source of Glass
    GLLINK TEXT,                              -- Link to Glass purchase
    GLSIMG TEXT,                              -- Link to picture of Glass
    GLSNOTE TEXT,                             -- Note for Glass
    FOREIGN KEY (GLSTEX) REFERENCES GTL(GLSTEX) ON DELETE SET NULL ON UPDATE CASCADE,
    FOREIGN KEY (GLSOURCE) REFERENCES GSL(GLSOURCE) ON DELETE SET NULL ON UPDATE CASCADE
);

-- ITM: Item Names
CREATE TABLE IF NOT EXISTS ITM (
    ITEMID INTEGER PRIMARY KEY AUTOINCREMENT, -- PID of item
    ITMNAME TEXT,                             -- Name of piece
    ITMIMG TEXT,                              -- Path to image
    ONEOFF INTEGER,                           -- One off item (0/1)
    VARIAT INTEGER,                           -- Variations (0/1)
    ITMGRP TEXT,                              -- Item group
    VARIID INTEGER,                           -- Variation of Item
    CURRENT INTEGER,                          -- Item currently being sold (0/1)
    ITMPTRN TEXT,                             -- Link to Pattern IMG
    ITMNOTE TEXT,                             -- Notes about item
    FOREIGN KEY (ITMGRP) REFERENCES IGP(ITMGRP) ON DELETE SET NULL ON UPDATE CASCADE,
    FOREIGN KEY (VARIID) REFERENCES IVR(VARIID) ON DELETE SET NULL ON UPDATE CASCADE
);

-- IPC: Price Tracking of Items
CREATE TABLE IF NOT EXISTS IPC (
    ITEMID INTEGER,                           -- PID of item
    ITMPRICE NUMERIC,                         -- Price of Item
    STDATE TEXT,                              -- Pricing Start Date
    ENDDATE TEXT,                             -- Pricing End Date
    FOREIGN KEY (ITEMID) REFERENCES ITM(ITEMID) ON DELETE CASCADE ON UPDATE CASCADE
);

-- GPC: Price Tracking of Glass
CREATE TABLE IF NOT EXISTS GPC (
    GLASSID INTEGER,                          -- PID of Glass
    GLSPRICE NUMERIC,                         -- Price of Glass
    STDATE TEXT,                              -- Pricing Start Date
    ENDDATE TEXT,                             -- Pricing End Date
    FOREIGN KEY (GLASSID) REFERENCES GSI(GLASSID) ON DELETE CASCADE ON UPDATE CASCADE
);

-- IGC: Item Glass Components
CREATE TABLE IF NOT EXISTS IGC (
    COMPID INTEGER,                           -- PID of Component
    ITEMID INTEGER,                           -- PID of Item
    COMPNUM INTEGER,                          -- Comp number in pattern
    GLASSID INTEGER,                          -- GlassID (mapped from GLI)
    COMPLEN NUMERIC,                          -- COMP width Bounding box
    COMPWID NUMERIC,                          -- Comp Length Bounding box
    COMPNOTE TEXT,                            -- Note about Specific Component
    PRIMARY KEY (COMPID, ITEMID),
    FOREIGN KEY (ITEMID) REFERENCES ITM(ITEMID) ON DELETE CASCADE ON UPDATE CASCADE,
    FOREIGN KEY (GLASSID) REFERENCES GSI(GLASSID) ON DELETE SET NULL ON UPDATE CASCADE
);

-- ICC: Inventory Current Count
CREATE TABLE IF NOT EXISTS ICC (
    ITEMID INTEGER PRIMARY KEY,               -- ItemID
    IPCUT INTEGER DEFAULT 0,                  -- Items done at Cutting
    IPGRND INTEGER DEFAULT 0,                 -- Items done at Grinding
    IPFOIL INTEGER DEFAULT 0,                 -- Items done at Foiling
    IPSLDR INTEGER DEFAULT 0,                 -- Items done at Soldering
    IPDONE INTEGER DEFAULT 0,                 -- Items Completed
    IPTS TEXT DEFAULT CURRENT_TIMESTAMP,      -- TimeStamp last updated
    FOREIGN KEY (ITEMID) REFERENCES ITM(ITEMID) ON DELETE CASCADE ON UPDATE CASCADE
);

-- ITR: Inventory Transaction Record
CREATE TABLE IF NOT EXISTS ITR (
    ITRID INTEGER PRIMARY KEY AUTOINCREMENT,  -- Item Transaction Record ID
    ITEMID INTEGER,                           -- ItemID
    IPCUT INTEGER DEFAULT 0,                  -- Items done at Cutting
    IPGRND INTEGER DEFAULT 0,                 -- Items done at Grinding
    IPFOIL INTEGER DEFAULT 0,                 -- Items done at Foiling
    IPSLDR INTEGER DEFAULT 0,                 -- Items done at Soldering
    IPDONE INTEGER DEFAULT 0,                 -- Items Completed
    IPTS TEXT DEFAULT CURRENT_TIMESTAMP,      -- TimeStamp last updated
    FOREIGN KEY (ITEMID) REFERENCES ITM(ITEMID) ON DELETE CASCADE ON UPDATE CASCADE
);

-- ITMSALE: Item Sales
CREATE TABLE IF NOT EXISTS ITMSALE (
    SALEID INTEGER PRIMARY KEY AUTOINCREMENT, -- Sales ID
    ITEMID INTEGER,                           -- Item ID
    SUNITS INTEGER,                           -- Units Sold
    SDATE TEXT,                               -- Date Sold
    VENUEID INTEGER,                          -- Venue
    FOREIGN KEY (ITEMID) REFERENCES ITM(ITEMID) ON DELETE RESTRICT ON UPDATE CASCADE,
    FOREIGN KEY (VENUEID) REFERENCES VENUE(VENUEID) ON DELETE RESTRICT ON UPDATE CASCADE
);

-- TIMESALE: Time-based Sales
CREATE TABLE IF NOT EXISTS TIMESALE (
    TSALEID INTEGER PRIMARY KEY AUTOINCREMENT, -- Sales ID
    TSTIME TEXT,                              -- Time of Sale
    TSUNITS INTEGER,                          -- Units Sold
    TSDATE TEXT,                              -- Date Sold
    VENUEID INTEGER,                          -- Venue
    FOREIGN KEY (VENUEID) REFERENCES VENUE(VENUEID) ON DELETE RESTRICT ON UPDATE CASCADE
);
