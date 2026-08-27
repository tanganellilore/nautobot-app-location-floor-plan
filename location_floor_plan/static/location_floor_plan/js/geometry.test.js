// Basic geometry tests using jest
require('./location_floor_plan.js'); // need to eval or mock L

describe('Geometry Mapping', () => {
    // We cannot fully test Leaflet instances without a full mock, but we can test backendToLeaflet
    
    // Quick and dirty mock of L to allow file import
    beforeAll(() => {
        global.L = {
            polygon: jest.fn(),
            rectangle: jest.fn(),
            CRS: { Simple: {} },
            map: jest.fn(),
            imageOverlay: jest.fn(),
            layerGroup: jest.fn()
        };
        // Load the file so global.LocationFloorPlanGeometry is populated
        require('./location_floor_plan.js');
    });

    test('backend polygon to leaflet points', () => {
        const backendGeom = { type: 'polygon', points: [[10, 20], [30, 40]] };
        const leafletGeom = global.LocationFloorPlanGeometry.backendToLeaflet(backendGeom);
        expect(leafletGeom).toEqual([[20, 10], [40, 30]]); // y,x
    });

    test('backend rectangle to leaflet bounds', () => {
        const backendGeom = { x: 5, y: 15, width: 25, height: 35 };
        const leafletGeom = global.LocationFloorPlanGeometry.backendToLeaflet(backendGeom);
        // sw: [y, x], ne: [y+height, x+width]
        expect(leafletGeom).toEqual([[15, 5], [50, 30]]);
    });
});
